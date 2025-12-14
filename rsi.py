# rsi_app.py
# =============================================================================
# Приложение для RSI:
#  - признаки (X) на окне lookback,
#  - метрики (Sharpe, Sum),
#  - стратегия по RSI,
#  - разметка y на форварде,
#  - сетка параметров RSI,
#  - CLI: сбор датасета, обучение CatBoost, рекомендация, отчёт на последнем форвард-окне.
# Вся общая ML-логика (walk-forward, обучение CatBoost) — в rolling_catboost.py
# =============================================================================

# Запуск:
#   python rsi.py --csv '.\data\21.10.2024 13.00.00 - 21.10.2025 13.00.00\YDEX_2H_20241021_130000_20251021_130000.csv'
# Полезные параметры:
#   --lookback 1000 --horizon 100 --step 20 --cost_bps 5
#   --periods 9,14,21 --bands 20-80,30-70   (переопределить сетку)
# (параметры CatBoost переопределяются только в формате key=val через --cat_overrides)

import argparse
import numpy as np
import pandas as pd
from rolling_catboost import (load_csv, acf1_safe, build_dataset, time_split_by_ratio, prepare_eval_set_unseen, fit_catboost_multiclass, build_catboost_params, sharpe_and_sum,)


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
# ПРИЗНАКИ X: из окна lookback по Close И по Open/High/Low/Volume - из последнего окна (по умолчанию 1000 баров) возвращает набор «режимных» фич: по Close: mean/std доходностей, ACF1, наклон тренда лог-цены, RSI(14) mean/std, по High/Low: средний относительный диапазон, «фитиль» свечей (верхний/нижний), по True Range: средний относительный TR (приближённый ATR/price), по Open-Close: доля бычьих свечей, средний относительный (Close-Open)/Open, по Volume: среднее/стд лог-объёма, отношение коротк./длинн. объёма, corr(|ret|, vol).
def make_features_ohlcv_rsi(df_window: pd.DataFrame, lookback: int = 1000) -> pd.Series:
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


# СЕТКА ПАРАМЕТРОВ: компактная по умолчанию, но можно переопределить через CLI - генерит список словарей {"period": p, "lower": lo, "upper": up}.
def make_grid_rsi(periods=None, bands=None):
    if periods is None:
        periods = [9, 14, 21]
    if bands is None:
        bands = [(20, 80), (30, 70)]
    return [{"period": p, "lower": lo, "upper": up} for p in periods for (lo, up) in bands]


# РАЗМЕТКА y: лучший класс параметров на форвард-окне - для момента start берёт окно (для X), затем на следующем куске horizon перебирает все варианты из сетки и ставит метку класса = «индекс лучшего набора» по (Sharpe, Sum).
def make_labeler_rsi(grid, cost_bps: float):
    def label_on_forward(df: pd.DataFrame, start: int, lookback: int, horizon: int):
        # X из окна [start-lookback, start)
        X = make_features_ohlcv_rsi(df.iloc[start - lookback:start], lookback)

        # Y — победившая комбинация на форварде [start, start+horizon)
        fw_close = df["close"].iloc[start:start + horizon]
        scores = []
        for i, g in enumerate(grid):
            rsi = compute_rsi(fw_close, g["period"]).fillna(50.0)
            strat = rsi_strategy_returns(fw_close, rsi, g["lower"], g["upper"], cost_bps)
            sh, sm = sharpe_and_sum(strat)
            scores.append((i, sh, sm))
        best_idx, _, _ = max(scores, key=lambda t: (t[1], t[2]))
        return X, best_idx
    return label_on_forward


def parse_cli_grid(periods_arg: str, bands_arg: str):
    # Сетка параметров через CLI (опционально)
    periods = [int(x) for x in periods_arg.split(",")] if periods_arg and periods_arg.strip() else None
    if bands_arg and bands_arg.strip():
        b = []
        for token in bands_arg.split(","):
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
    return periods, bands

# Основной пайплайн (загрузка данных -> фичи -> CatBoost -> выбор параметров RSI). 
# Возвращает структуру с результатами, чтобы ею можно было пользоваться в ноутбуках.
def run_pipeline(args, verbose: bool = True):

    def _arg(name, default=None):
        if isinstance(args, dict):
            return args.get(name, default)
        return getattr(args, name, default)

    def _log(*msg, **kwargs): # вкл/выкл сообщения через verbose: bool
        if verbose:
            print(*msg, **kwargs)

    csv_path = _arg("csv")
    if not csv_path:
        raise ValueError("Не указан путь к CSV (--csv).")

    lookback = int(_arg("lookback", 1000))
    horizon = int(_arg("horizon", 100))
    step = int(_arg("step", 20))
    cost_bps = float(_arg("cost_bps", 5.0))
    periods_arg = _arg("periods", "")
    bands_arg = _arg("bands", "")
    overrides = _arg("cat_overrides", "")
    plot_flag = bool(_arg("plot", False))

    df = load_csv(csv_path)

    periods, bands = parse_cli_grid(periods_arg, bands_arg)
    grid = make_grid_rsi(periods, bands)

    _log("Карта классов:")
    for i, g in enumerate(grid):
        _log(i, g)

    label_fn = make_labeler_rsi(grid, cost_bps)
    X, y = build_dataset(df, lookback=lookback, horizon=horizon, step=step, label_fn=label_fn) # идёт по истории с шагом step, берёт окна длины lookback, формирует (X, y) через label_fn
    if len(X) < 10:
        raise RuntimeError("Слишком мало образцов. Нужна более длинная история или уменьшить lookback/horizon.")

    Xtr, ytr, Xte, yte = time_split_by_ratio(X, y, valid_ratio=0.2)                            # разбивает получившийся датасет на обучающую и валидационную части по времени.
    eval_set = prepare_eval_set_unseen(Xte, yte, ytr)                                          # подчищает eval‑сэт от классов, которых не было в train
    cat_params = build_catboost_params(overrides_str=overrides)                                # берёт базовые параметры из default_catboost_params() (iterations, depth, loss_function, баланс классов и т.д.) и позволяет частично их переопределять строкой вида depth=5, iterations=2500, learning_rate=0.04

    if eval_set is None:
        model, holdout_acc = fit_catboost_multiclass(Xtr, ytr, None, None, params=cat_params, plot_fit=plot_flag)
    else:
        Xte_eval, yte_eval = eval_set
        model, holdout_acc = fit_catboost_multiclass(Xtr, ytr, Xte_eval, yte_eval, params=cat_params, plot_fit=plot_flag)

    _log(f"Holdout accuracy: {holdout_acc}")

    lb_df = df.iloc[-(lookback + horizon):-horizon]
    X_last = make_features_ohlcv_rsi(lb_df, lookback).to_frame().T
    pred_last = int(model.predict(X_last).flatten()[0])
    best_params = grid[pred_last]
    _log("Рекомендованные параметры RSI:", best_params)

    fw_close = df["close"].iloc[-horizon:]
    rsi_rec = compute_rsi(fw_close, best_params["period"]).fillna(50.0)
    ret_rec = rsi_strategy_returns(fw_close, rsi_rec, best_params["lower"], best_params["upper"], cost_bps=cost_bps)
    sh_rec, sm_rec = sharpe_and_sum(ret_rec)

    rsi_base = compute_rsi(fw_close, 14).fillna(50.0)
    ret_base = rsi_strategy_returns(fw_close, rsi_base, 30, 70, cost_bps=cost_bps)
    sh_base, sm_base = sharpe_and_sum(ret_base)

    _log("Последнее форвард-окно:")
    _log(f"  Рекомендация: Sharpe={sh_rec:.3f}, Sum={sm_rec:.4f}")
    _log(f"  База 14/30-70: Sharpe={sh_base:.3f}, Sum={sm_base:.4f}")

    return {
        "df": df,
        "grid": grid,
        "model": model,
        "holdout_acc": holdout_acc,
        "best_index": pred_last,
        "best_params": best_params,
        "forward_close": fw_close,
        "forward_rsi": rsi_rec,
        "forward_returns": ret_rec,
        "forward_metrics": {"sharpe": sh_rec, "sum": sm_rec},
        "baseline_rsi": rsi_base,
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
    ap.add_argument("--periods", type=str, default="", help="Сетка периодов RSI, напр.: 9,14,21")
    ap.add_argument("--bands", type=str, default="", help="Сетка порогов, напр.: 20-80,30-70")
    ap.add_argument("--cat_overrides", type=str, default="", help="Переопределения CatBoost (key=val через запятую), напр.: depth=5,iterations=2500,learning_rate=0.04")

    args = ap.parse_args()
    run_pipeline(args, verbose=True)


if __name__ == "__main__":
    main()
