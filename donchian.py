# donchian.py
# =============================================================================
# Подбор оптимальных параметров Donchian Channel:
#  - формируем датасет по скользящим окнам (lookback/horizon/step),
#  - размечаем классом = лучший период канала (Sharpe, затем Sum) на форварде,
#  - обучаем CatBoostClassifier на классах,
#  - выбираем оптимальный период Donchian на последнем окне и сравниваем с базовым.
# Общая ML-логика (walk-forward, CatBoost) в rolling_catboost.py
# =============================================================================

import argparse
from types import SimpleNamespace
from typing import Callable, Tuple
import numpy as np
import pandas as pd
from rolling_catboost import (load_csv, acf1_safe, build_dataset, time_split_by_ratio, prepare_eval_set_unseen, fit_catboost_multiclass, build_catboost_params,)


def compute_donchian(high: pd.Series, low: pd.Series, period: int) -> pd.DataFrame:  # Верхняя/нижняя линии Donchian(period)
    upper = high.rolling(period, min_periods=1).max()
    lower = low.rolling(period, min_periods=1).min()
    mid = (upper + lower) / 2.0
    return pd.DataFrame({"upper": upper, "lower": lower, "mid": mid})


# Стратегия: пробой/возврат: long при выходе выше верхней, short при выходе ниже нижней, выход при обратном пересечении, с учётом комиссии.
def donchian_strategy_returns(close: pd.Series, dc: pd.DataFrame, cost_bps: float = 5.0) -> pd.Series:  
    r = close.pct_change().fillna(0.0).values
    upper = dc["upper"].values
    lower = dc["lower"].values
    n = len(close)
    pos = np.zeros(n, dtype=int)
    trades = np.zeros(n, dtype=int)
    cost = cost_bps / 10000.0
    curr = 0
    for t in range(1, n):
        new = curr
        if curr == 0:
            if close.iloc[t - 1] <= upper[t - 1] and close.iloc[t] > upper[t]:
                new = 1
            elif close.iloc[t - 1] >= lower[t - 1] and close.iloc[t] < lower[t]:
                new = -1
            else:
                mid_prev = (upper[t - 1] + lower[t - 1]) / 2.0
                if close.iloc[t] > mid_prev:
                    new = 1
                elif close.iloc[t] < mid_prev:
                    new = -1
        elif curr == 1:
            if close.iloc[t - 1] >= lower[t - 1] and close.iloc[t] < lower[t]:
                new = 0
        elif curr == -1:
            if close.iloc[t - 1] <= upper[t - 1] and close.iloc[t] > upper[t]:
                new = 0
        if new != curr:
            trades[t] = 1
            curr = new
        pos[t] = curr
    strat = np.insert(pos[:-1] * r[1:], 0, 0.0)
    strat -= trades * cost * np.abs(np.diff(np.insert(pos, 0, 0)))
    return pd.Series(strat, index=close.index)


def sharpe_and_sum(ret: pd.Series) -> Tuple[float, float]:  # Метрики: Sharpe и сумма доходности
    r = ret.dropna()
    if len(r) < 3:
        return 0.0, float(r.sum())
    mu = float(r.mean())
    sd = float(r.std(ddof=0))
    return mu / (sd + 1e-12), float(r.sum())


def make_features_ohlcv_dc(df_window: pd.DataFrame, lookback: int = 1000) -> pd.Series:  # Фичи по последнему окну (цена/объём/диапазоны)
    w = df_window.iloc[-lookback:].copy()
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in w.columns:
            if col == "volume":
                w[col] = 0.0
            else:
                w[col] = w["close"]

    close = w["close"].astype(float)
    open_ = w["open"].astype(float)
    high = w["high"].astype(float)
    low = w["low"].astype(float)
    vol = w["volume"].astype(float)

    ret = close.pct_change().fillna(0.0)
    mu = float(ret.mean())
    sd = float(ret.std(ddof=0))
    acf = acf1_safe(ret)

    x = np.arange(len(close))
    if len(close) > 1:
        log_close = np.log(close.replace(0, np.nan)).ffill().bfill()
        slope_logp = float(np.polyfit(x, log_close, 1)[0])
    else:
        slope_logp = 0.0

    rng_rel = (high - low) / (close.replace(0, np.nan) + 1e-12)
    range_mean = float(rng_rel.mean())
    range_std = float(rng_rel.std(ddof=0))

    upper_wick = (high - np.maximum(open_, close)) / (close + 1e-12)
    lower_wick = (np.minimum(open_, close) - low) / (close + 1e-12)
    uw_mean = float(upper_wick.clip(lower=0).mean())
    lw_mean = float(lower_wick.clip(lower=0).mean())

    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1) / (prev_close.replace(0, np.nan) + 1e-12)
    tr_mean = float(tr.replace([np.inf, -np.inf], np.nan).fillna(0.0).mean())

    logv = np.log(vol.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    logv_mean = float(logv.mean())
    logv_std = float(logv.std(ddof=0))
    short = max(20, min(100, len(vol) // 5))
    vol_ratio = float(vol.rolling(short).mean().iloc[-1] / (vol.mean() + 1e-12)) if len(vol) > short else 1.0
    corr_absret_vol = float(pd.concat([ret.abs(), vol], axis=1).corr().iloc[0, 1]) if ret.notna().sum() > 5 and vol.notna().sum() > 5 else 0.0

    feats = {
        "mu": mu,
        "sd": sd,
        "acf1": acf,
        "slope_logp": slope_logp,
        "range_mean": range_mean,
        "range_std": range_std,
        "upper_wick_mean": uw_mean,
        "lower_wick_mean": lw_mean,
        "tr_mean": tr_mean,
        "logv_mean": logv_mean,
        "logv_std": logv_std,
        "vol_ratio": vol_ratio,
        "corr_absret_vol": corr_absret_vol,
    }
    return pd.Series(feats)


def make_grid_dc(periods=None):  # Сетка периодов Donchian Channel
    if periods is None:
        periods = [10, 20, 30, 40, 50, 60, 70, 80]
    return [{"period": p} for p in periods]


def make_labeler_dc(grid, cost_bps: float) -> Callable:  # label_fn: лучшая EMA по Sharpe/Sum на форварде
    def label_on_forward(df: pd.DataFrame, start: int, lookback: int, horizon: int):
        X = make_features_ohlcv_dc(df.iloc[start - lookback:start], lookback)
        fw = df.iloc[start:start + horizon]
        h = fw["high"] if "high" in fw else fw["close"]
        l = fw["low"] if "low" in fw else fw["close"]
        c = fw["close"]
        scores = []
        for i, g in enumerate(grid):
            dc = compute_donchian(h, l, g["period"])
            strat = donchian_strategy_returns(c, dc, cost_bps=cost_bps)
            sh, sm = sharpe_and_sum(strat)
            scores.append((i, sh, sm))
        best_idx, _, _ = max(scores, key=lambda t: (t[1], t[2]))
        return X, best_idx

    return label_on_forward


def parse_cli_dc_periods(periods_arg: str):  # Парсер сетки периодов из CLI
    if periods_arg and periods_arg.strip():
        return [int(x) for x in periods_arg.split(",")]
    return None


def run_pipeline(args, verbose: bool = True):  # Основной пайплайн Donchian Channel

    def _arg(name, default=None):
        if isinstance(args, dict):
            return args.get(name, default)
        return getattr(args, name, default)

    def _log(*msg, **kwargs):
        if verbose:
            print(*msg, **kwargs)

    csv_path = _arg("csv")
    if not csv_path:
        raise ValueError("Не указан путь к CSV (--csv).")

    lookback = int(_arg("lookback", 1000))
    horizon = int(_arg("horizon", 100))
    step = int(_arg("step", 20))
    cost_bps = float(_arg("cost_bps", 5.0))
    periods_arg = _arg("dc_periods", "")
    overrides = _arg("cat_overrides", "")
    plot_flag = bool(_arg("plot", False))

    df = load_csv(csv_path)
    periods = parse_cli_dc_periods(periods_arg)
    grid = make_grid_dc(periods)

    _log("Карта классов:")
    for i, g in enumerate(grid):
        _log(i, g)

    label_fn = make_labeler_dc(grid, cost_bps)
    X, y = build_dataset(df, lookback=lookback, horizon=horizon, step=step, label_fn=label_fn)
    if len(X) < 10:
        raise RuntimeError("Слишком мало примеров. Увеличьте историю или уменьшите lookback/horizon.")
    if y.nunique() < 2:
        _log(f"В выборке один класс: {y.iloc[0]}. Используем его без CatBoost.") # если разметка во всех окнах выбирает один и тот же период
        best_idx = int(y.iloc[0])
        best_params = grid[best_idx]
        lb_df = df.iloc[-(lookback + horizon):-horizon]
        X_last = make_features_ohlcv_dc(lb_df, lookback).to_frame().T
        fw_close = df["close"].iloc[-horizon:]
        fw_high = df["high"].iloc[-horizon:] if "high" in df else fw_close
        fw_low = df["low"].iloc[-horizon:] if "low" in df else fw_close
        dc_rec = compute_donchian(fw_high, fw_low, best_params["period"])
        ret_rec = donchian_strategy_returns(fw_close, dc_rec, cost_bps=cost_bps)
        sh_rec, sm_rec = sharpe_and_sum(ret_rec)

        dc_base = compute_donchian(fw_high, fw_low, 20)
        ret_base = donchian_strategy_returns(fw_close, dc_base, cost_bps=cost_bps)
        sh_base, sm_base = sharpe_and_sum(ret_base)

        _log("Последнее форвард-окно (fallback, один класс):")
        _log(f"  Рекомендация: Sharpe={sh_rec:.3f}, Sum={sm_rec:.4f}")
        _log(f"  База 20: Sharpe={sh_base:.3f}, Sum={sm_base:.4f}")

        return {
            "df": df,
            "grid": grid,
            "model": None,
            "holdout_acc": None,
            "best_index": best_idx,
            "best_params": best_params,
            "forward_close": fw_close,
            "forward_dc": dc_rec,
            "forward_returns": ret_rec,
            "forward_metrics": {"sharpe": sh_rec, "sum": sm_rec},
            "baseline_dc": dc_base,
            "baseline_returns": ret_base,
            "baseline_metrics": {"sharpe": sh_base, "sum": sm_base},
        }

    Xtr, ytr, Xte, yte = time_split_by_ratio(X, y, valid_ratio=0.2)
    eval_set = prepare_eval_set_unseen(Xte, yte, ytr)
    cat_params = build_catboost_params(overrides_str=overrides)

    if eval_set is None:
        model, holdout_acc = fit_catboost_multiclass(Xtr, ytr, None, None, params=cat_params, plot_fit=plot_flag)
    else:
        Xte_eval, yte_eval = eval_set
        model, holdout_acc = fit_catboost_multiclass(Xtr, ytr, Xte_eval, yte_eval, params=cat_params, plot_fit=plot_flag)

    _log(f"Holdout accuracy: {holdout_acc}")

    lb_df = df.iloc[-(lookback + horizon):-horizon]
    X_last = make_features_ohlcv_dc(lb_df, lookback).to_frame().T
    h_last = lb_df["high"] if "high" in lb_df else lb_df["close"]
    l_last = lb_df["low"] if "low" in lb_df else lb_df["close"]
    pred_last = int(model.predict(X_last).flatten()[0])
    best_params = grid[pred_last]
    _log("Рекомендованные параметры Donchian:", best_params)

    fw_close = df["close"].iloc[-horizon:]
    fw_high = df["high"].iloc[-horizon:] if "high" in df else fw_close
    fw_low = df["low"].iloc[-horizon:] if "low" in df else fw_close
    dc_rec = compute_donchian(fw_high, fw_low, best_params["period"])
    ret_rec = donchian_strategy_returns(fw_close, dc_rec, cost_bps=cost_bps)
    sh_rec, sm_rec = sharpe_and_sum(ret_rec)

    dc_base = compute_donchian(fw_high, fw_low, 20)
    ret_base = donchian_strategy_returns(fw_close, dc_base, cost_bps=cost_bps)
    sh_base, sm_base = sharpe_and_sum(ret_base)

    _log("Последнее форвард-окно:")
    _log(f"  Рекомендация: Sharpe={sh_rec:.3f}, Sum={sm_rec:.4f}")
    _log(f"  База 20: Sharpe={sh_base:.3f}, Sum={sm_base:.4f}")

    return {
        "df": df,
        "grid": grid,
        "model": model,
        "holdout_acc": holdout_acc,
        "best_index": pred_last,
        "best_params": best_params,
        "forward_close": fw_close,
        "forward_dc": dc_rec,
        "forward_returns": ret_rec,
        "forward_metrics": {"sharpe": sh_rec, "sum": sm_rec},
        "baseline_dc": dc_base,
        "baseline_returns": ret_base,
        "baseline_metrics": {"sharpe": sh_base, "sum": sm_base},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=str, required=True, help="Путь к CSV (OHLCV)")
    ap.add_argument("--lookback", type=int, default=1000, help="Длина окна истории для фич")
    ap.add_argument("--horizon", type=int, default=100, help="Длина форвард-окна для разметки/оценки")
    ap.add_argument("--step", type=int, default=20, help="Шаг окна при сборе датасета")
    ap.add_argument("--cost_bps", type=float, default=5.0, help="Комиссия (б.п.) на смену позиции")
    ap.add_argument("--dc_periods", type=str, default="", help="Сетка периодов Donchian, напр.: 10,20,30")
    ap.add_argument("--cat_overrides", type=str, default="", help="Переопределения CatBoost (key=val через запятую)")
    ap.add_argument("--plot", action="store_true", help="Показать CatBoost MetricVisualizer (ipywidgets)")

    args = ap.parse_args()
    run_pipeline(args, verbose=True)


if __name__ == "__main__":
    main()
