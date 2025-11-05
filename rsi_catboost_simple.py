# Запуск:
#   python rsi_catboost_simple.py --csv path/to/file.csv
# Полезные параметры:
#   --lookback 1000 --horizon 100 --step 20 --cost_bps 5
#   --periods 9,14,21 --bands 20-80;30-70   (переопределить сетку)

import argparse
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier


# ВСПОМОГАТЕЛЬНОЕ: безопасная автокорреляция лаг=1 - аккуратно считает автокорреляцию ряда с лагом 1 (ACF1) (меряем «память» доходностей — часто близко к нулю, но полезно как фича).
def acf1_safe(x: pd.Series) -> float:
    x = pd.Series(x).dropna()
    if len(x) < 3:
        return 0.0
    x0, x1 = x.iloc[:-1], x.iloc[1:]
    den = float(x.std(ddof=0)) ** 2 * (len(x) - 1)
    if den <= 0:
        return 0.0
    return float(((x0 - x.mean()) * (x1 - x.mean())).sum() / den)


# ИНДИКАТОР: RSI по Уайлдеру - считает RSI (0..100) экспоненциальным сглаживанием приращений.
def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / (loss + 1e-12)
    return 100 - (100 / (1 + rs))


# СТРАТЕГИЯ: простая mean-reversion по кроссам порогов RSI - моделирует торговлю — long при «выходе из перепроданности», short при «выходе из перекупленности» (позиция применяется на следующей свече; учтены транзакционные издержки (б.п. на смену позиции)).
def rsi_strategy_returns(close: pd.Series, rsi: pd.Series, lower: float, upper: float, cost_bps: float = 5.0) -> pd.Series:
    r = close.pct_change().fillna(0.0).values
    x = rsi.values
    n = len(close)
    pos = np.zeros(n, dtype=int)
    trades = np.zeros(n, dtype=int)
    cost = cost_bps / 10000.0
    curr = 0
    for t in range(1, n):
        new = curr
        if curr == 0:
            if x[t-1] <= lower and x[t] > lower: new = 1
            elif x[t-1] >= upper and x[t] < upper: new = -1
        elif curr == 1:
            if x[t-1] <= upper and x[t] > upper: new = 0
        elif curr == -1:
            if x[t-1] >= lower and x[t] < lower: new = 0
        if new != curr:
            trades[t] = 1
            curr = new
        pos[t] = curr
    strat = np.insert(pos[:-1] * r[1:], 0, 0.0)
    strat -= trades * cost * np.abs(np.diff(np.insert(pos, 0, 0)))
    return pd.Series(strat, index=close.index)


# МЕТРИКИ: Sharpe и сумма доходностей - возвращает Sharpe≈mean/std (не годовой) и Sum (сумма доходностей), выбираем лучший набор параметров по (Sharpe, затем Sum).
def sharpe_and_sum(ret: pd.Series):
    r = ret.dropna()
    if len(r) < 3:
        return 0.0, float(r.sum())
    mu = float(r.mean())
    sd = float(r.std(ddof=0))
    return mu / (sd + 1e-12), float(r.sum())


# ПРИЗНАКИ X: из окна lookback по Close И по Open/High/Low/Volume - из последнего окна (по умолчанию 1000 баров) возвращает набор «режимных» фич: по Close: mean/std доходностей, ACF1, наклон тренда лог-цены, RSI(14) mean/std, по High/Low: средний относительный диапазон, «фитиль» свечей (верхний/нижний), по True Range: средний относительный TR (приближённый ATR/price), по Open-Close: доля бычьих свечей, средний относительный (Close-Open)/Open, по Volume: среднее/стд лог-объёма, отношение коротк./длинн. объёма, corr(|ret|, vol).
def make_features_ohlcv(df: pd.DataFrame, lookback: int = 1000) -> pd.Series:
    w = df.iloc[-lookback:].copy()

    # Гарантируем нужные колонки (если чего-то нет — делаем безопасные заглушки)
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in w.columns:
            if col == "volume":
                w[col] = 0.0
            else:
                w[col] = w["close"]

    close = w["close"].astype(float)
    high  = w["high"].astype(float)
    low   = w["low"].astype(float)
    open_ = w["open"].astype(float)
    vol   = w["volume"].astype(float)

    # --- Блок по Close
    ret = close.pct_change()
    mu = float(ret.mean())
    sd = float(ret.std(ddof=0))
    acf = acf1_safe(ret)
    s = np.log(close.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).ffill().bfill()
    x = np.arange(len(s))
    slope_logp = float(np.polyfit(x, s.values, 1)[0])
    rsi14 = compute_rsi(close, 14)
    rsi_mean = float(rsi14.mean())
    rsi_std  = float(rsi14.std(ddof=0))

    # --- Блок по High/Low/диапазонам
    rng_rel = (high - low) / (close.replace(0, np.nan) + 1e-12)
    range_mean = float(rng_rel.mean())
    range_std  = float(rng_rel.std(ddof=0))

    upper_wick = (high - np.maximum(open_, close)) / (close + 1e-12)
    lower_wick = (np.minimum(open_, close) - low)   / (close + 1e-12)
    uw_mean = float(upper_wick.clip(lower=0).mean())
    lw_mean = float(lower_wick.clip(lower=0).mean())

    # --- True Range (относительный), приближённо
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low  - prev_close).abs()
    ], axis=1).max(axis=1) / (prev_close.replace(0, np.nan) + 1e-12)
    tr_mean = float(tr.replace([np.inf, -np.inf], np.nan).fillna(0.0).mean())

    # --- Open-Close
    up_ratio = float((close > open_).mean())
    oc_ret_mean = float(((close - open_) / (open_.replace(0, np.nan) + 1e-12)).replace([np.inf, -np.inf], np.nan).fillna(0.0).mean())

    # --- Volume
    logv = np.log(vol.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    logv_mean = float(logv.mean())
    logv_std  = float(logv.std(ddof=0))
    short = max(20, min(100, len(vol)//5))  # короткое окно 20..100 баров
    vol_ratio = float(vol.rolling(short).mean().iloc[-1] / (vol.mean() + 1e-12)) if len(vol) > short else 1.0
    corr_absret_vol = float(pd.concat([ret.abs(), vol], axis=1).corr().iloc[0,1]) if ret.notna().sum() > 5 and vol.notna().sum() > 5 else 0.0

    feats = {
        # Close
        "mu": mu, "sd": sd, "acf1": acf, "slope_logp": slope_logp,
        "rsi_mean": rsi_mean, "rsi_std": rsi_std,
        # High/Low
        "range_mean": range_mean, "range_std": range_std,
        "upper_wick_mean": uw_mean, "lower_wick_mean": lw_mean,
        # True Range
        "tr_mean": tr_mean,
        # Open-Close
        "up_ratio": up_ratio, "oc_ret_mean": oc_ret_mean,
        # Volume
        "logv_mean": logv_mean, "logv_std": logv_std,
        "vol_ratio": vol_ratio, "corr_absret_vol": corr_absret_vol,
    }
    return pd.Series(feats)


# РАЗМЕТКА y: лучший класс параметров на форвард-окне - для момента start берёт окно (для X), затем на следующем куске horizon перебирает все варианты из сетки и ставит метку класса = «индекс лучшего набора» по (Sharpe, Sum).
def label_on_forward(df: pd.DataFrame, start: int, lookback: int, horizon: int, grid, cost_bps=5.0):
    X = make_features_ohlcv(df.iloc[start-lookback:start], lookback)
    fw_close = df["close"].iloc[start:start+horizon]
    scores = []
    for i, g in enumerate(grid):
        rsi = compute_rsi(fw_close, g["period"]).fillna(50.0)
        strat = rsi_strategy_returns(fw_close, rsi, g["lower"], g["upper"], cost_bps)
        sh, sm = sharpe_and_sum(strat)
        scores.append((i, sh, sm))
    best_idx, _, _ = max(scores, key=lambda t: (t[1], t[2]))
    return X, best_idx


# СЕТКА ПАРАМЕТРОВ: компактная по умолчанию, но можно переопределить через CLI - генерит список словарей {"period": p, "lower": lo, "upper": up}.
def make_grid(periods=None, bands=None):
    if periods is None:
        periods = [9, 14, 21]
    if bands is None:
        bands = [(20, 80), (30, 70)]
    return [{"period": p, "lower": lo, "upper": up} for p in periods for (lo, up) in bands]


# ДАТАСЕТ: формируем (X, y) скользящими окнами - идём по истории с шагом step — на каждом шаге считаем X из окна и y из форварда.
def build_dataset(df: pd.DataFrame, lookback=1000, horizon=100, step=20, cost_bps=5.0, periods=None, bands=None):
    grid = make_grid(periods, bands)
    X_rows, y_rows = [], []
    for t in range(lookback, len(df) - horizon, step):
        X, y = label_on_forward(df, t, lookback, horizon, grid, cost_bps)
        X_rows.append(X); y_rows.append(y)
    X_df = pd.DataFrame(X_rows).reset_index(drop=True)
    y_ser = pd.Series(y_rows, name="label")
    return X_df, y_ser, grid


# ЗАГРУЗКА CSV: аккуратно читаем OHLCV и приводим к единому виду - удаляет «Unnamed»/пустые колонки, находит колонку времени, сортирует по времени, приводит имена к нижнему регистру и возвращает DataFrame с хотя бы close (open/high/low/volume — опционально).
def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    # 1) Удаляем «Unnamed»/пустые колонки (например, индекс 0,1,2,...)
    bad = df.columns.astype(str).str.match(r'Unnamed: ?\d*|^$')
    if bad.any():
        df = df.loc[:, ~bad]

    # 2) Находим колонку времени
    time_cols = [c for c in df.columns if str(c).lower() in ("time","timestamp","date","datetime")]
    tcol = time_cols[0] if len(time_cols) else df.columns[0]
    df["__dt__"] = pd.to_datetime(df[tcol], utc=True, errors="coerce")
    df = df.dropna(subset=["__dt__"]).set_index("__dt__").sort_index()

    # 3) Приводим имена к нижнему регистру
    df.columns = [str(c).lower() for c in df.columns]

    # 4) Проверяем наличие close
    if "close" not in df.columns:
        raise ValueError("В CSV нет колонки 'close'")

    # 5) Оставляем только полезные столбцы, но НЕ выкидываем отсутствующие — ими займёмся в фичах
    keep = [c for c in ["open","high","low","close","volume"] if c in df.columns]
    return df[keep]


# ТОЧКА ВХОДА: обучение модели и отчёт по последнему форвард-окну
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=str, required=True, help="Путь к CSV одной акции (OHLCV)")
    ap.add_argument("--lookback", type=int, default=1000, help="Длина окна истории для фич")
    ap.add_argument("--horizon", type=int, default=100, help="Длина форвард-окна для разметки/оценки")
    ap.add_argument("--step", type=int, default=20, help="Шаг окна при сборе датасета")
    ap.add_argument("--cost_bps", type=float, default=5.0, help="Комиссия (б.п.) на смену позиции")
    ap.add_argument("--periods", type=str, default="", help="Сетка периодов RSI, напр.: 9,14,21")
    ap.add_argument("--bands", type=str, default="", help="Сетка порогов, напр.: 20-80,30-70") 
    args = ap.parse_args()

    # Сетка параметров через CLI (опционально)
    periods = [int(x) for x in args.periods.split(",")] if args.periods.strip() else None
    if args.bands.strip():
        b = []
        for token in args.bands.split(","):
            token = token.strip()
            if not token:
                continue
            if "-" in token:
                parts = [p.strip() for p in token.split("-", 1)]
                if len(parts) == 2 and parts[0] and parts[1]:
                    b.append((int(parts[0]), int(parts[1])))
        bands = b if b else None
    else:
        bands = None

    # Загружаем данные OHLCV
    df = load_csv(args.csv)

    # Собираем (X, y)
    X, y, grid = build_dataset(df, args.lookback, args.horizon, args.step, args.cost_bps, periods, bands)
    if len(X) < 10:
        raise RuntimeError("Слишком мало образцов. Нужна более длинная история или уменьшить lookback/horizon.")

    # Покажем сопоставление «класс → параметры»
    print("Карта классов:")
    for i, g in enumerate(grid):
        print(i, g)

    # Сплит по времени 80/20
    n_train = int(len(X) * 0.8)
    Xtr, ytr = X.iloc[:n_train], y.iloc[:n_train]
    Xte, yte = X.iloc[n_train:], y.iloc[n_train:]

    # Диагностика unseen-классов в валидации
    train_classes = set(ytr.unique())
    test_classes  = set(yte.unique())
    unseen_in_test = sorted(c for c in test_classes if c not in train_classes)
    if unseen_in_test:
        print(f"[INFO] В тесте есть классы, отсутствующие в обучении: {unseen_in_test}")
        mask = yte.isin(list(train_classes))
        Xte_eval, yte_eval = Xte[mask], yte[mask]
        if len(Xte_eval) == 0:
            print("[INFO] Все тестовые классы отсутствуют в обучении. Обучим без eval_set.")
            eval_set = None
        else:
            eval_set = (Xte_eval, yte_eval)
            print(f"[INFO] Оставлено в валидации после фильтра: {len(Xte_eval)} из {len(Xte)}")
    else:
        eval_set = (Xte, yte)

    # Обучаем CatBoost
    model = CatBoostClassifier(
        iterations=100,             # сколько «слабых деревьев» добавляем последовательно
        depth=6,                    # максимальная глубина каждого дерева (сложность правила)
        learning_rate=0.1,         # «шаг» бустинга (чем меньше, тем стабильнее, но нужно больше итераций)
        loss_function="MultiClass", # многоклассовая кросс-энтропия (подходит для нашей задачи)
        eval_metric="MultiClass",   # что мониторим на валидации
        random_seed=1,              # воспроизводимость
        allow_writing_files=False   # не писать catboost_info/*
    )                               # verbose=100 # печать прогресса
    if eval_set is None:
        model.fit(Xtr, ytr)
        holdout_acc = None
    else:
        model.fit(Xtr, ytr, eval_set=eval_set, use_best_model=True)
        Xte_eval, yte_eval = eval_set
        pred_eval = model.predict(Xte_eval).flatten().astype(int)
        holdout_acc = float((pred_eval == yte_eval.values).mean())
    print(f"Holdout accuracy: {holdout_acc}")

    # Рекомендация на самом конце (последнее окно lookback)
    lb_df = df.iloc[-(args.lookback + args.horizon):-args.horizon]
    X_last = make_features_ohlcv(lb_df, args.lookback).to_frame().T
    pred_last = int(model.predict(X_last).flatten()[0])
    params = grid[pred_last]
    print("Рекомендованные параметры RSI:", params)

    # Честная оценка на последнем форвард-окне (следующие horizon баров)
    fw_close = df["close"].iloc[-args.horizon:]
    rsi_rec = compute_rsi(fw_close, params["period"]).fillna(50.0)
    ret_rec = rsi_strategy_returns(fw_close, rsi_rec, params["lower"], params["upper"], cost_bps=args.cost_bps)
    sh_rec, sm_rec = sharpe_and_sum(ret_rec)

    # База: RSI(14, 30/70)
    rsi_base = compute_rsi(fw_close, 14).fillna(50.0)
    ret_base = rsi_strategy_returns(fw_close, rsi_base, 30, 70, cost_bps=args.cost_bps)
    sh_base, sm_base = sharpe_and_sum(ret_base)

    print("Последнее форвард-окно:")
    print(f"  Рекомендация: Sharpe={sh_rec:.3f}, Sum={sm_rec:.4f}")
    print(f"  База 14/30-70: Sharpe={sh_base:.3f}, Sum={sm_base:.4f}")


if __name__ == "__main__":
    main()