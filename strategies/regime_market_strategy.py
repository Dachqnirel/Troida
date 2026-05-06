#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from itertools import product
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

UTC = timezone.utc


@dataclass(slots=True)
class StrategyParams:
    trend_adx_threshold: float = 25.0
    range_adx_threshold: float = 20.0
    bear_adx_threshold: float = 20.0
    range_bb_lookback: int = 50

    trend_rsi_min: float = 50.0
    trend_rsi_max: float = 70.0
    trend_relvol_min: float = 1.0
    trend_stop_atr_mult: float = 2.0
    trend_take_atr_mult: float = 4.0
    trend_exit_rsi: float = 75.0

    range_entry_rsi: float = 35.0
    range_entry_relvol_min: float = 0.7
    range_stop_atr_mult: float = 1.5
    range_fallback_take_atr_mult: float = 2.0
    range_exit_rsi: float = 55.0


@dataclass(slots=True)
class BacktestConfig:
    initial_cash: float = 100_000.0
    commission: float = 0.0005
    slippage: float = 0.0003


REQUIRED_COLUMNS = [
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
    "SMA_50",
    "SMA_200",
    "ADX_14",
    "ATR_14",
    "RSI_14",
    "BB_Upper",
    "BB_Middle",
    "BB_Lower",
    "BB_Width",
    "RelativeVolume",
]


def _validate_columns(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"В df отсутствуют обязательные колонки: {missing}")


def _market_regime(df: pd.DataFrame, p: StrategyParams) -> pd.Series:
    bb_width_mean_50 = df["BB_Width"].rolling(p.range_bb_lookback, min_periods=p.range_bb_lookback).mean()

    trend_mask = (
        (df["ADX_14"] > p.trend_adx_threshold)
        & (df["Close"] > df["SMA_200"])
        & (df["SMA_50"] > df["SMA_200"])
    )

    range_mask = (
        (df["ADX_14"] < p.range_adx_threshold)
        & (df["BB_Width"] < bb_width_mean_50)
        & (df["Close"] >= df["BB_Lower"])
        & (df["Close"] <= df["BB_Upper"])
    )

    bear_mask = (
        (df["Close"] < df["SMA_200"])
        & (df["SMA_50"] < df["SMA_200"])
        & (df["ADX_14"] > p.bear_adx_threshold)
    )

    regime = pd.Series("NEUTRAL", index=df.index, dtype="object")
    regime.loc[bear_mask] = "BEAR"
    regime.loc[range_mask] = "RANGE"
    regime.loc[trend_mask] = "TREND"
    return regime


def _apply_strategy_with_params(df: pd.DataFrame, p: StrategyParams) -> pd.DataFrame:
    _validate_columns(df)

    out = df.copy()
    out["MarketRegime"] = _market_regime(out, p)

    out["EntryRegime"] = None
    out["Signal"] = None
    out["Position"] = 0
    out["EntryPrice"] = np.nan
    out["StopLoss"] = np.nan
    out["TakeProfit"] = np.nan
    out["ExitReason"] = None

    in_position = False
    entry_regime: str | None = None
    entry_price = np.nan
    stop_loss = np.nan
    take_profit = np.nan

    for i in range(len(out)):
        row = out.iloc[i]
        close = float(row["Close"])
        low = float(row["Low"])
        atr = float(row["ATR_14"])
        sma_50 = float(row["SMA_50"])
        rsi = float(row["RSI_14"])
        bb_mid = float(row["BB_Middle"])
        bb_low = float(row["BB_Lower"])
        rel_vol = float(row["RelativeVolume"])
        regime = str(row["MarketRegime"])

        prev_close = float(out.iloc[i - 1]["Close"]) if i > 0 else np.nan

        signal = None
        exit_reason = None

        if in_position:
            if entry_regime == "TREND":
                if close < sma_50:
                    exit_reason = "CloseBelowSMA50"
                elif (rsi > p.trend_exit_rsi) and (i > 0) and (close < prev_close):
                    exit_reason = "RSIOverheatReversal"
                elif close <= stop_loss:
                    exit_reason = "StopLoss"
                elif close >= take_profit:
                    exit_reason = "TakeProfit"

            elif entry_regime == "RANGE":
                if close >= bb_mid:
                    exit_reason = "ReachedBBMiddle"
                elif rsi > p.range_exit_rsi:
                    exit_reason = "RSIExit"
                elif close <= stop_loss:
                    exit_reason = "StopLoss"
                elif close >= take_profit:
                    exit_reason = "TakeProfit"

            if exit_reason is not None:
                signal = "SELL"
                in_position = False
                entry_regime = None
                entry_price = np.nan
                stop_loss = np.nan
                take_profit = np.nan

        if not in_position:
            trend_entry = (
                regime == "TREND"
                and close > sma_50
                and rsi > p.trend_rsi_min
                and rsi < p.trend_rsi_max
                and rel_vol > p.trend_relvol_min
                and (i > 0 and close > prev_close)
            )

            range_entry = (
                regime == "RANGE"
                and close <= bb_low
                and rsi < p.range_entry_rsi
                and rel_vol > p.range_entry_relvol_min
                and close > low
            )

            if trend_entry:
                signal = "BUY"
                in_position = True
                entry_regime = "TREND"
                entry_price = close
                stop_loss = entry_price - p.trend_stop_atr_mult * atr
                take_profit = entry_price + p.trend_take_atr_mult * atr

            elif range_entry:
                signal = "BUY"
                in_position = True
                entry_regime = "RANGE"
                entry_price = close
                stop_loss = entry_price - p.range_stop_atr_mult * atr
                take_profit = bb_mid if bb_mid >= entry_price else entry_price + p.range_fallback_take_atr_mult * atr

        out.iat[i, out.columns.get_loc("Signal")] = signal
        out.iat[i, out.columns.get_loc("Position")] = 1 if in_position else 0
        out.iat[i, out.columns.get_loc("EntryRegime")] = entry_regime
        out.iat[i, out.columns.get_loc("EntryPrice")] = entry_price
        out.iat[i, out.columns.get_loc("StopLoss")] = stop_loss
        out.iat[i, out.columns.get_loc("TakeProfit")] = take_profit
        out.iat[i, out.columns.get_loc("ExitReason")] = exit_reason

    return out


def apply_strategy(df: pd.DataFrame) -> pd.DataFrame:
    return _apply_strategy_with_params(df, StrategyParams())


def run_backtest(df_with_signals: pd.DataFrame, cfg: BacktestConfig) -> dict[str, Any]:
    cash = float(cfg.initial_cash)
    shares = 0.0
    entry_cost = 0.0

    equity_curve: list[float] = []
    trade_pnls: list[float] = []

    for _, row in df_with_signals.iterrows():
        close = float(row["Close"])
        signal = row["Signal"]

        if signal == "BUY" and shares == 0:
            exec_price = close * (1.0 + cfg.slippage)
            qty = cash / (exec_price * (1.0 + cfg.commission))
            if qty > 0:
                shares = qty
                entry_cost = cash
                cash = 0.0

        elif signal == "SELL" and shares > 0:
            exec_price = close * (1.0 - cfg.slippage)
            gross = shares * exec_price
            cash = gross * (1.0 - cfg.commission)
            pnl = cash - entry_cost
            trade_pnls.append(pnl)
            shares = 0.0
            entry_cost = 0.0

        equity = cash + shares * close
        equity_curve.append(equity)

    if shares > 0:
        last_close = float(df_with_signals["Close"].iloc[-1])
        cash = shares * last_close * (1.0 - cfg.commission)
        pnl = cash - entry_cost
        trade_pnls.append(pnl)
        shares = 0.0
        equity_curve[-1] = cash

    equity_series = pd.Series(equity_curve, index=df_with_signals.index)
    ret = equity_series.pct_change().fillna(0.0)

    years = max((df_with_signals.index[-1] - df_with_signals.index[0]).days / 365.25, 1e-9)
    final_value = float(equity_series.iloc[-1])
    total_return = (final_value / cfg.initial_cash - 1.0) * 100.0
    cagr = ((final_value / cfg.initial_cash) ** (1.0 / years) - 1.0) * 100.0

    rolling_max = equity_series.cummax()
    drawdown = (equity_series / rolling_max - 1.0) * 100.0
    max_dd = float(drawdown.min())

    sharpe = np.nan
    if ret.std() > 0:
        sharpe = float((ret.mean() / ret.std()) * np.sqrt(252))

    closed_trades = len(trade_pnls)
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]

    win_rate = (len(wins) / closed_trades * 100.0) if closed_trades > 0 else 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    gross_profit = float(np.sum(wins)) if wins else 0.0
    gross_loss_abs = abs(float(np.sum(losses))) if losses else 0.0
    profit_factor = (gross_profit / gross_loss_abs) if gross_loss_abs > 0 else float("inf")
    expectancy = float(np.mean(trade_pnls)) if trade_pnls else 0.0

    return {
        "period_start": df_with_signals.index[0],
        "period_end": df_with_signals.index[-1],
        "initial_cash": cfg.initial_cash,
        "final_value": final_value,
        "total_return_pct": total_return,
        "cagr_pct": cagr,
        "max_drawdown_pct": abs(max_dd),
        "sharpe_ratio": sharpe,
        "trades": closed_trades,
        "win_rate_pct": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
    }


def _rma(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1 / period, adjust=False).mean()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out = out.rename(columns={
        "Open": "Open",
        "High": "High",
        "Low": "Low",
        "Close": "Close",
        "Volume": "Volume",
    })

    out["SMA_50"] = out["Close"].rolling(50, min_periods=50).mean()
    out["SMA_200"] = out["Close"].rolling(200, min_periods=200).mean()

    prev_close = out["Close"].shift(1)
    tr = pd.concat([
        out["High"] - out["Low"],
        (out["High"] - prev_close).abs(),
        (out["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    out["ATR_14"] = _rma(tr, 14)

    delta = out["Close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = _rma(gain, 14)
    avg_loss = _rma(loss, 14)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out["RSI_14"] = 100.0 - (100.0 / (1.0 + rs))

    up_move = out["High"].diff()
    down_move = -out["Low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=out.index)
    minus_dm = pd.Series(minus_dm, index=out.index)

    plus_di = 100.0 * _rma(plus_dm, 14) / out["ATR_14"].replace(0, np.nan)
    minus_di = 100.0 * _rma(minus_dm, 14) / out["ATR_14"].replace(0, np.nan)
    dx = (100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    out["ADX_14"] = _rma(dx, 14)

    bb_period = 20
    bb_std = out["Close"].rolling(bb_period, min_periods=bb_period).std(ddof=0)
    out["BB_Middle"] = out["Close"].rolling(bb_period, min_periods=bb_period).mean()
    out["BB_Upper"] = out["BB_Middle"] + 2.0 * bb_std
    out["BB_Lower"] = out["BB_Middle"] - 2.0 * bb_std
    out["BB_Width"] = (out["BB_Upper"] - out["BB_Lower"]) / out["BB_Middle"].replace(0, np.nan)

    vol_ma = out["Volume"].rolling(20, min_periods=20).mean()
    out["RelativeVolume"] = out["Volume"] / vol_ma.replace(0, np.nan)

    out = out.dropna(subset=REQUIRED_COLUMNS).copy()
    return out


def load_yfinance_ohlcv(symbol: str, since: str) -> pd.DataFrame:
    raw = yf.download(symbol, start=since, interval="1d", auto_adjust=False, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("Не удалось загрузить данные из yfinance")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] for c in raw.columns]
    raw = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    if raw.index.tz is None:
        raw.index = raw.index.tz_localize(UTC)
    else:
        raw.index = raw.index.tz_convert(UTC)
    raw = raw[~raw.index.duplicated(keep="last")]
    return raw


def optimize_parameters(df: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    grid = {
        "trend_adx_threshold": [20.0, 25.0, 30.0],
        "range_adx_threshold": [18.0, 22.0],
        "trend_rsi_max": [70.0, 75.0],
        "trend_relvol_min": [0.9, 1.0],
        "trend_stop_atr_mult": [1.5, 2.0],
        "trend_take_atr_mult": [3.0, 4.0],
        "range_entry_rsi": [30.0, 35.0],
        "range_stop_atr_mult": [1.0, 1.5],
        "range_exit_rsi": [55.0, 60.0],
    }

    base = StrategyParams()
    rows: list[dict[str, Any]] = []

    total = int(np.prod([len(v) for v in grid.values()]))
    for idx, vals in enumerate(product(*grid.values()), start=1):
        p = replace(
            base,
            trend_adx_threshold=vals[0],
            range_adx_threshold=vals[1],
            trend_rsi_max=vals[2],
            trend_relvol_min=vals[3],
            trend_stop_atr_mult=vals[4],
            trend_take_atr_mult=vals[5],
            range_entry_rsi=vals[6],
            range_stop_atr_mult=vals[7],
            range_exit_rsi=vals[8],
        )
        sig_df = _apply_strategy_with_params(df, p)
        m = run_backtest(sig_df, cfg)
        rows.append({
            "cagr_pct": m["cagr_pct"],
            "total_return_pct": m["total_return_pct"],
            "max_drawdown_pct": m["max_drawdown_pct"],
            "trades": m["trades"],
            "params": p,
        })
        if idx % 100 == 0:
            print(f"Оптимизация: {idx}/{total}")

    res = pd.DataFrame(rows)
    res = res.sort_values(["cagr_pct", "total_return_pct"], ascending=False).reset_index(drop=True)
    return res


def _print_metrics(title: str, m: dict[str, Any]) -> None:
    print(f"\n===== {title} =====")
    print(f"Период:                 {m['period_start'].date()} -> {m['period_end'].date()}")
    print(f"Начальный капитал:      {m['initial_cash']:.2f}")
    print(f"Финальный капитал:      {m['final_value']:.2f}")
    print(f"Итоговая доходность:    {m['total_return_pct']:.2f}%")
    print(f"CAGR (годовых):         {m['cagr_pct']:.2f}%")
    print(f"Max Drawdown:           {m['max_drawdown_pct']:.2f}%")
    print(f"Sharpe Ratio:           {m['sharpe_ratio']:.4f}" if not np.isnan(m['sharpe_ratio']) else "Sharpe Ratio:           nan")
    print(f"Количество сделок:      {m['trades']}")
    print(f"Win Rate:               {m['win_rate_pct']:.2f}%")
    print(f"Average Win:            {m['avg_win']:.2f}")
    print(f"Average Loss:           {m['avg_loss']:.2f}")
    print(f"Profit Factor:          {m['profit_factor']:.4f}")
    print(f"Expectancy / trade:     {m['expectancy']:.2f}")
    print("================================")


def main() -> None:
    symbol = "AAPL"
    since = "2024-01-01"

    raw = load_yfinance_ohlcv(symbol=symbol, since=since)
    df = compute_indicators(raw)

    strat_df = apply_strategy(df)
    cfg = BacktestConfig()
    base_metrics = run_backtest(strat_df, cfg)
    _print_metrics("БАЗОВАЯ СТРАТЕГИЯ", base_metrics)

    opt = optimize_parameters(df, cfg)
    best = opt.iloc[0]
    best_params: StrategyParams = best["params"]

    print("\n===== ТОП-10 ПАРАМЕТРОВ ПО CAGR =====")
    for i, row in opt.head(10).iterrows():
        p: StrategyParams = row["params"]
        print(
            f"{i+1:2d}. CAGR={row['cagr_pct']:.2f}% Ret={row['total_return_pct']:.2f}% DD={row['max_drawdown_pct']:.2f}% Trades={int(row['trades'])} "
            f"| tADX>{p.trend_adx_threshold:.0f} rADX<{p.range_adx_threshold:.0f} rsiMax={p.trend_rsi_max:.0f} relVol>{p.trend_relvol_min:.1f} "
            f"tSL={p.trend_stop_atr_mult:.1f} tTP={p.trend_take_atr_mult:.1f} rRSI<{p.range_entry_rsi:.0f} rSL={p.range_stop_atr_mult:.1f} rExitRSI>{p.range_exit_rsi:.0f}"
        )

    best_df = _apply_strategy_with_params(df, best_params)
    best_metrics = run_backtest(best_df, cfg)
    _print_metrics("ЛУЧШАЯ КОМБИНАЦИЯ", best_metrics)

    if best_metrics["cagr_pct"] >= 8.0:
        print("\nЦель достигнута: CAGR >= 8%")
    else:
        print("\nЦель не достигнута: CAGR < 8%")


if __name__ == "__main__":
    main()
