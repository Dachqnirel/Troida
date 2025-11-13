# macd.py
# =============================================================================
# Приложение для MACD:
#  - признаки (X) на окне lookback,
#  - метрики (Sharpe, Sum),
#  - стратегия по MACD (пересечения основной линии и сигнальной),
#  - разметка y на форварде,
#  - сетка параметров MACD (fast, slow, signal),
#  - CLI: сбор датасета, обучение CatBoost, рекомендация, отчёт на последнем форвард-окне.
# Вся общая ML-логика (walk-forward, обучение CatBoost) — в rolling_catboost.py
# =============================================================================

# Запуск:
#   python macd.py --csv path/to/file.csv
# Полезные параметры:
#   --lookback 1000 --horizon 100 --step 20 --cost_bps 5
#   --macd_fast 8,12,16 --macd_slow 20,26,30 --macd_signal 5,9
#   --cat_overrides depth=5,iterations=3000
# (параметры CatBoost переопределяются только в формате key=val через --cat_overrides)

import argparse
import numpy as np
import pandas as pd
from rolling_catboost import (load_csv, acf1_safe, build_dataset, time_split_by_ratio, prepare_eval_set_unseen, fit_catboost_multiclass, build_catboost_params,)


# ИНДИКАТОР: MACD (Moving Average Convergence Divergence) - основная линия = EMA(fast) - EMA(slow); сигнальная = EMA(основной линии, signal)
def _ema(x: pd.Series, period: int) -> pd.Series:
    return x.ewm(span=period, adjust=False).mean()

# по умолчанию быстрая скользящая средняя рассчитывается за 12 свечей, а медленная — за 26,
# сигнальная линия - сглаженная линия MACD. Если signal = 9, то при дневном tf сигнальная линия будет сглаживаться по значениям 9 торговых дней, а при часовом tf — 9 торговых часов.
def compute_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    fast_ema = _ema(close, fast)
    slow_ema = _ema(close, slow)
    macd = fast_ema - slow_ema # значение линии MACD в конкретной точке графика: MACD = Быстрая скользящая средняя − Медленная скользящая средняя
    signal_line = macd.ewm(span=signal, adjust=False).mean() # сглаженная линия MACD
    hist = macd - signal_line
    return pd.DataFrame({"macd": macd, "signal": signal_line, "hist": hist})


# СТРАТЕГИЯ: пересечения основной линии MACD и сигнальной - long при пересечении снизу вверх, short при пересечении сверху вниз (позиция применяется на следующей свече; учтены транзакционные издержки (б.п. на смену позиции)).
def macd_strategy_returns(close: pd.Series, macd_df: pd.DataFrame, cost_bps: float = 5.0) -> pd.Series:
    r = close.pct_change().fillna(0.0).values
    macd = macd_df["macd"].values
    sig  = macd_df["signal"].values
    n = len(close)
    pos = np.zeros(n, dtype=int)
    trades = np.zeros(n, dtype=int)
    cost = cost_bps / 10000.0
    curr = 0
    for t in range(1, n):
        new = curr
        # сигналы на пересечениях macd и сигнальной
        if curr == 0:
            if macd[t-1] <= sig[t-1] and macd[t] > sig[t]:  # бычье пересечение
                new = 1
            elif macd[t-1] >= sig[t-1] and macd[t] < sig[t]:  # медвежье пересечение
                new = -1
        elif curr == 1:
            # выход при обратном пересечении вниз
            if macd[t-1] >= sig[t-1] and macd[t] < sig[t]:
                new = 0
        elif curr == -1:
            # выход при обратном пересечении вверх
            if macd[t-1] <= sig[t-1] and macd[t] > sig[t]:
                new = 0
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


# ПРИЗНАКИ X: из окна lookback по Close И по Open/High/Low/Volume - набор «режимных» фич как в RSI-версии,
# но вместо статистик RSI добавим статистики по MACD/Signal (mean/std последних значений).
def make_features_ohlcv_macd(df_window: pd.DataFrame, lookback: int = 1000) -> pd.Series:
    w = df_window.iloc[-lookback:].copy()

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

    # MACD(12,26,9) "дефолтный" для фичей
    macd_df = compute_macd(close, 12, 26, 9)
    macd_mean = float(macd_df["macd"].mean())
    macd_std  = float(macd_df["macd"].std(ddof=0))
    sig_mean  = float(macd_df["signal"].mean())
    sig_std   = float(macd_df["signal"].std(ddof=0))
    hist_mean = float(macd_df["hist"].mean())
    hist_std  = float(macd_df["hist"].std(ddof=0))

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
        # MACD stats
        "macd_mean": macd_mean, "macd_std": macd_std,
        "macd_signal_mean": sig_mean, "macd_signal_std": sig_std,
        "macd_hist_mean": hist_mean, "macd_hist_std": hist_std,
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


# СЕТКА ПАРАМЕТРОВ: MACD по умолчанию, но можно переопределить через CLI - генерит список словарей {"fast": f, "slow": s, "signal": g}.
def make_grid_macd(fasts=None, slows=None, signals=None):
    if fasts is None:
        fasts = [8, 12, 16]
    if slows is None:
        slows = [20, 26, 30]
    if signals is None:
        signals = [5, 9]
    # классический MACD требует fast < slow - фильтруем пары
    grid = []
    for f in fasts:
        for s in slows:
            if f >= s:
                continue
            for g in signals:
                grid.append({"fast": f, "slow": s, "signal": g})
    return grid


# РАЗМЕТКА y: лучший класс параметров на форвард-окне - для момента start берёт окно (для X), затем на следующем куске horizon перебирает все варианты из сетки и ставит метку класса = «индекс лучшего набора» по (Sharpe, затем Sum).
def make_labeler_macd(grid, cost_bps: float):
    def label_on_forward(df: pd.DataFrame, start: int, lookback: int, horizon: int):
        # X из окна [start-lookback, start)
        X = make_features_ohlcv_macd(df.iloc[start - lookback:start], lookback)

        # Y — победившая комбинация на форварде [start, start+horizon)
        fw_close = df["close"].iloc[start:start + horizon]
        scores = []
        for i, g in enumerate(grid):
            macd_df = compute_macd(fw_close, g["fast"], g["slow"], g["signal"])
            strat = macd_strategy_returns(fw_close, macd_df, cost_bps)
            sh, sm = sharpe_and_sum(strat)
            scores.append((i, sh, sm))
        best_idx, _, _ = max(scores, key=lambda t: (t[1], t[2]))
        return X, best_idx
    return label_on_forward


def parse_cli_macd_grids(fast_arg: str, slow_arg: str, signal_arg: str):
    # Сетка параметров через CLI (опционально), формат: "8,12,16", "20,26,30", "5,9"
    fasts = [int(x) for x in fast_arg.split(",")] if fast_arg and fast_arg.strip() else None
    slows = [int(x) for x in slow_arg.split(",")] if slow_arg and slow_arg.strip() else None
    signals = [int(x) for x in signal_arg.split(",")] if signal_arg and signal_arg.strip() else None
    return fasts, slows, signals


# Основной пайплайн (загрузка данных -> фичи -> CatBoost -> выбор параметров MACD).
# Возвращает структуру с результатами, чтобы ею можно было пользоваться в ноутбуках.
def run_pipeline(args, verbose: bool = True):

    def _arg(name, default=None):
        if isinstance(args, dict):
            return args.get(name, default)
        return getattr(args, name, default)

    def _log(*msg, **kwargs):  # вкл/выкл сообщения через verbose: bool
        if verbose:
            print(*msg, **kwargs)

    csv_path = _arg("csv")
    if not csv_path:
        raise ValueError("Не указан путь к CSV (--csv).")

    lookback = int(_arg("lookback", 1000))
    horizon = int(_arg("horizon", 100))
    step = int(_arg("step", 20))
    cost_bps = float(_arg("cost_bps", 5.0))
    fast_arg = _arg("macd_fast", "")
    slow_arg = _arg("macd_slow", "")
    signal_arg = _arg("macd_signal", "")
    overrides = _arg("cat_overrides", "")
    plot_flag = bool(_arg("plot", False))

    df = load_csv(csv_path)

    fasts, slows, signals = parse_cli_macd_grids(fast_arg, slow_arg, signal_arg)
    grid = make_grid_macd(fasts, slows, signals)

    _log("Карта классов:")
    for i, g in enumerate(grid):
        _log(i, g)

    label_fn = make_labeler_macd(grid, cost_bps)
    X, y = build_dataset(df, lookback=lookback, horizon=horizon, step=step, label_fn=label_fn) # идёт по истории с шагом step, берёт окна длины lookback, формирует (X, y) через label_fn
    if len(X) < 10:
        raise RuntimeError("Слишком мало образцов. Нужна более длинная история или уменьшить lookback/horizon.")

    Xtr, ytr, Xte, yte = time_split_by_ratio(X, y, valid_ratio=0.2)                            # разбивает получившийся датасет на обучающую и валидационную части по времени
    eval_set = prepare_eval_set_unseen(Xte, yte, ytr)                                          # подчищает eval‑сэт от классов, которых не было в train
    cat_params = build_catboost_params(overrides_str=overrides)                                # берёт базовые параметры из default_catboost_params() (iterations, depth, loss_function, баланс классов и т.д.) и позволяет частично их переопределять строкой вида depth=5, iterations=2500, learning_rate=0.04

    if eval_set is None:
        model, holdout_acc = fit_catboost_multiclass(Xtr, ytr, None, None, params=cat_params, plot_fit=plot_flag)
    else:
        Xte_eval, yte_eval = eval_set
        model, holdout_acc = fit_catboost_multiclass(Xtr, ytr, Xte_eval, yte_eval, params=cat_params, plot_fit=plot_flag)

    _log(f"Holdout accuracy: {holdout_acc}")

    lb_df = df.iloc[-(lookback + horizon):-horizon]
    X_last = make_features_ohlcv_macd(lb_df, lookback).to_frame().T
    pred_last = int(model.predict(X_last).flatten()[0])
    best_params = grid[pred_last]
    _log("Рекомендованные параметры MACD:", best_params)

    fw_close = df["close"].iloc[-horizon:]
    macd_df = compute_macd(fw_close, best_params["fast"], best_params["slow"], best_params["signal"])
    ret_rec = macd_strategy_returns(fw_close, macd_df, cost_bps=cost_bps)
    sh_rec, sm_rec = sharpe_and_sum(ret_rec)

    # База: классические MACD(12,26,9)
    macd_base = compute_macd(fw_close, 12, 26, 9)
    ret_base = macd_strategy_returns(fw_close, macd_base, cost_bps=cost_bps)
    sh_base, sm_base = sharpe_and_sum(ret_base)

    _log("Последнее форвард-окно:")
    _log(f"  Рекомендация: Sharpe={sh_rec:.3f}, Sum={sm_rec:.4f}")
    _log(f"  База 12-26-9: Sharpe={sh_base:.3f}, Sum={sm_base:.4f}")

    return {
        "df": df,
        "grid": grid,
        "model": model,
        "holdout_acc": holdout_acc,
        "best_index": pred_last,
        "best_params": best_params,
        "forward_close": fw_close,
        "forward_macd": macd_df,
        "forward_returns": ret_rec,
        "forward_metrics": {"sharpe": sh_rec, "sum": sm_rec},
        "baseline_macd": macd_base,
        "baseline_returns": ret_base,
        "baseline_metrics": {"sharpe": sh_base, "sum": sm_base},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=str, required=True, help="Путь к CSV одной акции (OHLCV)")
    ap.add_argument("--lookback", type=int, default=1000, help="Длина окна истории для фич")
    ap.add_argument("--horizon", type=int, default=100, help="Длина форвард-окна для разметки/оценки")
    ap.add_argument("--step", type=int, default=20, help="Шаг окна при сборе датасета")
    ap.add_argument("--cost_bps", type=float, default=5.0, help="Комиссия (б.п.) на смену позиции")
    # Гриды MACD как строки чисел через запятую
    ap.add_argument("--macd_fast", type=str, default="", help="Сетка fast EMA для MACD, напр.: 8,12,16")
    ap.add_argument("--macd_slow", type=str, default="", help="Сетка slow EMA для MACD, напр.: 20,26,30")
    ap.add_argument("--macd_signal", type=str, default="", help="Сетка signal EMA для MACD, напр.: 5,9")
    # Переопределения CatBoost (только key=val, через запятую)
    ap.add_argument("--cat_overrides", type=str, default="", help="Переопределения CatBoost (key=val через запятую), напр.: depth=5,iterations=2500,learning_rate=0.04")
    # Опционально включить интерактивные графики обучения CatBoost (если окружение поддерживает)
    ap.add_argument("--plot", action="store_true", help="Включить интерактивные графики обучения CatBoost (ipywidgets)")

    args = ap.parse_args()
    run_pipeline(args, verbose=True)


if __name__ == "__main__":
    main()