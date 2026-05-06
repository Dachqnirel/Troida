#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product
import random
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf


@dataclass(slots=True)
class StrategyParams:
    prev_low_window: int = 20
    prev_high_window: int = 10
    avg_range_window: int = 20
    volume_avg_window: int = 20

    close_location_min: float = 0.65
    range_multiplier: float = 1.1
    volume_ratio_min: float = 1.1

    stop_buffer_mult: float = 0.25
    fallback_rr: float = 2.0

    timeout_bars: int = 7

    strong_red_close_location_max: float = 0.35
    strong_red_volume_ratio_min: float = 1.2

    rsi_period: int = 14
    use_rsi_filter: bool = False
    rsi_entry_min: float = 35.0
    rsi_entry_max: float = 70.0
    rsi_exit_bear: float = 40.0

    kama_period: int = 10
    kama_fast: int = 2
    kama_slow: int = 30
    use_kama_filter: bool = False
    kama_entry_buffer: float = 1.0
    kama_exit_buffer: float = 1.0


@dataclass(slots=True)
class BacktestConfig:
    initial_cash: float = 100_000.0
    commission: float = 0.0005
    slippage: float = 0.0003


BASE_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _kama(close: pd.Series, period: int, fast: int, slow: int) -> pd.Series:
    change = (close - close.shift(period)).abs()
    volatility = close.diff().abs().rolling(period).sum()
    er = change / volatility.replace(0, np.nan)

    fast_sc = 2.0 / (fast + 1.0)
    slow_sc = 2.0 / (slow + 1.0)
    sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2

    kama = pd.Series(index=close.index, dtype=float)
    if len(close) == 0:
        return kama

    kama.iloc[0] = close.iloc[0]
    for i in range(1, len(close)):
        sc_i = sc.iloc[i]
        if pd.isna(sc_i):
            kama.iloc[i] = kama.iloc[i - 1]
        else:
            kama.iloc[i] = kama.iloc[i - 1] + sc_i * (close.iloc[i] - kama.iloc[i - 1])
    return kama


def _apply_strategy_with_params(df: pd.DataFrame, p: StrategyParams) -> pd.DataFrame:
    for c in BASE_COLUMNS:
        if c not in df.columns:
            raise ValueError(f"В df нет обязательной колонки: {c}")

    out = df.copy()

    out["PrevLow20"] = out["Low"].rolling(p.prev_low_window).min().shift(1)
    out["PrevHigh10"] = out["High"].rolling(p.prev_high_window).max().shift(1)

    out["CandleRange"] = out["High"] - out["Low"]
    out["AvgRange20"] = out["CandleRange"].rolling(p.avg_range_window).mean().shift(1)

    denom = out["High"] - out["Low"]
    out["CloseLocation"] = np.where(
        denom > 0,
        (out["Close"] - out["Low"]) / denom,
        0.5,
    )

    out["VolumeAvg20"] = out["Volume"].rolling(p.volume_avg_window).mean().shift(1)
    out["VolumeRatio"] = out["Volume"] / out["VolumeAvg20"]
    out["RSI"] = _rsi(out["Close"], p.rsi_period)
    out["KAMA"] = _kama(out["Close"], p.kama_period, p.kama_fast, p.kama_slow)

    out["Signal"] = None
    out["Position"] = 0
    out["EntryPrice"] = np.nan
    out["StopLoss"] = np.nan
    out["TakeProfit"] = np.nan
    out["BarsInTrade"] = 0
    out["ExitReason"] = None

    in_position = False
    entry_price = np.nan
    stop_loss = np.nan
    take_profit = np.nan
    bars_in_trade = 0
    initial_risk = np.nan

    for i in range(len(out)):
        row = out.iloc[i]

        prev_low20 = float(row["PrevLow20"]) if pd.notna(row["PrevLow20"]) else np.nan
        prev_high10 = float(row["PrevHigh10"]) if pd.notna(row["PrevHigh10"]) else np.nan
        avg_range20 = float(row["AvgRange20"]) if pd.notna(row["AvgRange20"]) else np.nan

        low = float(row["Low"])
        high = float(row["High"])
        open_ = float(row["Open"])
        close = float(row["Close"])
        candle_range = float(row["CandleRange"])
        close_loc = float(row["CloseLocation"])
        vol_ratio = float(row["VolumeRatio"]) if pd.notna(row["VolumeRatio"]) else np.nan
        rsi = float(row["RSI"]) if pd.notna(row["RSI"]) else np.nan
        kama = float(row["KAMA"]) if pd.notna(row["KAMA"]) else np.nan

        signal = None
        exit_reason = None

        if in_position:
            bars_in_trade += 1

            if pd.notna(initial_risk) and initial_risk > 0:
                if (close - entry_price) >= initial_risk:
                    stop_loss = max(stop_loss, entry_price)

            strong_red = (
                (close < open_)
                and (close_loc < p.strong_red_close_location_max)
                and pd.notna(vol_ratio)
                and (vol_ratio > p.strong_red_volume_ratio_min)
            )

            if close <= stop_loss:
                exit_reason = "StopLoss"
            elif close >= take_profit:
                exit_reason = "TakeProfit"
            elif bars_in_trade >= p.timeout_bars and close < take_profit:
                exit_reason = f"TimeExit{p.timeout_bars}Bars"
            elif pd.notna(prev_low20) and close < prev_low20:
                exit_reason = "CloseBelowPrevLow20"
            elif strong_red:
                exit_reason = "StrongRedCandle"
            elif p.use_rsi_filter and pd.notna(rsi) and rsi < p.rsi_exit_bear:
                exit_reason = "RSIWeakness"
            elif p.use_kama_filter and pd.notna(kama) and close < kama * p.kama_exit_buffer:
                exit_reason = "CloseBelowKAMA"

            if exit_reason is not None:
                signal = "SELL"
                in_position = False
                entry_price = np.nan
                stop_loss = np.nan
                take_profit = np.nan
                bars_in_trade = 0
                initial_risk = np.nan

        if not in_position:
            entry_ready = (
                pd.notna(prev_low20)
                and pd.notna(prev_high10)
                and pd.notna(avg_range20)
                and pd.notna(vol_ratio)
                and (low < prev_low20)
                and (close > prev_low20)
                and (close_loc > p.close_location_min)
                and (candle_range > avg_range20 * p.range_multiplier)
                and (vol_ratio > p.volume_ratio_min)
                and (close > open_)
                and (
                    (not p.use_rsi_filter)
                    or (pd.notna(rsi) and (rsi > p.rsi_entry_min) and (rsi < p.rsi_entry_max))
                )
                and (
                    (not p.use_kama_filter)
                    or (pd.notna(kama) and (close >= kama * p.kama_entry_buffer))
                )
            )

            if entry_ready:
                candidate_stop = low - p.stop_buffer_mult * avg_range20
                risk = close - candidate_stop

                if risk > 0:
                    signal = "BUY"
                    in_position = True
                    entry_price = close
                    stop_loss = candidate_stop
                    take_profit = prev_high10
                    if take_profit <= entry_price:
                        take_profit = entry_price + p.fallback_rr * risk
                    bars_in_trade = 0
                    initial_risk = risk

        out.iat[i, out.columns.get_loc("Signal")] = signal
        out.iat[i, out.columns.get_loc("Position")] = 1 if in_position else 0
        out.iat[i, out.columns.get_loc("EntryPrice")] = entry_price
        out.iat[i, out.columns.get_loc("StopLoss")] = stop_loss
        out.iat[i, out.columns.get_loc("TakeProfit")] = take_profit
        out.iat[i, out.columns.get_loc("BarsInTrade")] = bars_in_trade if in_position else 0
        out.iat[i, out.columns.get_loc("ExitReason")] = exit_reason

    return out


def apply_strategy(df: pd.DataFrame) -> pd.DataFrame:
    return _apply_strategy_with_params(df, StrategyParams())


def run_backtest(df_with_signals: pd.DataFrame, cfg: BacktestConfig) -> dict[str, Any]:
    cash = float(cfg.initial_cash)
    shares = 0.0
    trade_entry_value = 0.0

    equity_curve: list[float] = []
    trade_pnls: list[float] = []

    for _, row in df_with_signals.iterrows():
        close = float(row["Close"])
        signal = row["Signal"]

        if signal == "BUY" and shares == 0:
            buy_price = close * (1.0 + cfg.slippage)
            qty = cash / (buy_price * (1.0 + cfg.commission))
            if qty > 0:
                shares = qty
                trade_entry_value = cash
                cash = 0.0

        elif signal == "SELL" and shares > 0:
            sell_price = close * (1.0 - cfg.slippage)
            gross = shares * sell_price
            cash = gross * (1.0 - cfg.commission)
            trade_pnls.append(cash - trade_entry_value)
            shares = 0.0
            trade_entry_value = 0.0

        equity_curve.append(cash + shares * close)

    if shares > 0:
        last_close = float(df_with_signals["Close"].iloc[-1])
        cash = shares * last_close * (1.0 - cfg.commission)
        trade_pnls.append(cash - trade_entry_value)
        equity_curve[-1] = cash

    equity = pd.Series(equity_curve, index=df_with_signals.index)
    returns = equity.pct_change().fillna(0.0)

    years = max((df_with_signals.index[-1] - df_with_signals.index[0]).days / 365.25, 1e-9)
    final_value = float(equity.iloc[-1])
    total_return = (final_value / cfg.initial_cash - 1.0) * 100.0
    cagr = ((final_value / cfg.initial_cash) ** (1.0 / years) - 1.0) * 100.0

    rolling_max = equity.cummax()
    drawdown_pct = (equity / rolling_max - 1.0) * 100.0
    max_dd = abs(float(drawdown_pct.min()))

    sharpe = np.nan
    if returns.std() > 0:
        sharpe = float((returns.mean() / returns.std()) * np.sqrt(252))

    trades = len(trade_pnls)
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]

    win_rate = (len(wins) / trades * 100.0) if trades > 0 else 0.0
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
        "max_drawdown_pct": max_dd,
        "sharpe_ratio": sharpe,
        "trades": trades,
        "win_rate_pct": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
    }


def load_yfinance_ohlcv(symbol: str, since: str = "2020-01-01") -> pd.DataFrame:
    raw = yf.download(symbol, start=since, interval="1d", auto_adjust=False, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("Не удалось загрузить данные из yfinance")

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] for c in raw.columns]

    out = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    out = out[~out.index.duplicated(keep="last")]
    return out


def optimize_parameters(df: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    base = StrategyParams()
    random.seed(42)

    candidate = {
        "prev_low_window": [10, 12, 15, 20],
        "prev_high_window": [10, 12, 15],
        "avg_range_window": [14, 20],
        "volume_avg_window": [10, 20],
        "close_location_min": [0.60, 0.65, 0.70],
        "range_multiplier": [0.9, 1.0, 1.1, 1.2],
        "volume_ratio_min": [0.9, 1.0, 1.1, 1.2],
        "stop_buffer_mult": [0.20, 0.25, 0.30],
        "fallback_rr": [2.0, 3.0, 4.0],
        "timeout_bars": [7, 10, 14],
        "strong_red_close_location_max": [0.25, 0.35],
        "strong_red_volume_ratio_min": [1.0, 1.1, 1.2],
        "rsi_entry_min": [30.0, 35.0, 40.0],
        "rsi_entry_max": [65.0, 70.0, 75.0],
        "rsi_exit_bear": [35.0, 40.0, 45.0],
        "use_rsi_filter": [False, True],
        "kama_entry_buffer": [0.995, 1.0, 1.005],
        "kama_exit_buffer": [0.98, 0.99, 1.0],
        "use_kama_filter": [False, True],
    }

    rows: list[dict[str, Any]] = []
    trials = 2400
    for idx in range(1, trials + 1):
        p = replace(
            base,
            prev_low_window=random.choice(candidate["prev_low_window"]),
            prev_high_window=random.choice(candidate["prev_high_window"]),
            avg_range_window=random.choice(candidate["avg_range_window"]),
            volume_avg_window=random.choice(candidate["volume_avg_window"]),
            close_location_min=random.choice(candidate["close_location_min"]),
            range_multiplier=random.choice(candidate["range_multiplier"]),
            volume_ratio_min=random.choice(candidate["volume_ratio_min"]),
            stop_buffer_mult=random.choice(candidate["stop_buffer_mult"]),
            fallback_rr=random.choice(candidate["fallback_rr"]),
            timeout_bars=random.choice(candidate["timeout_bars"]),
            strong_red_close_location_max=random.choice(candidate["strong_red_close_location_max"]),
            strong_red_volume_ratio_min=random.choice(candidate["strong_red_volume_ratio_min"]),
            rsi_entry_min=random.choice(candidate["rsi_entry_min"]),
            rsi_entry_max=random.choice(candidate["rsi_entry_max"]),
            rsi_exit_bear=random.choice(candidate["rsi_exit_bear"]),
            use_rsi_filter=random.choice(candidate["use_rsi_filter"]),
            kama_entry_buffer=random.choice(candidate["kama_entry_buffer"]),
            kama_exit_buffer=random.choice(candidate["kama_exit_buffer"]),
            use_kama_filter=random.choice(candidate["use_kama_filter"]),
        )

        out = _apply_strategy_with_params(df, p)
        m = run_backtest(out, cfg)

        rows.append(
            {
                "cagr_pct": m["cagr_pct"],
                "total_return_pct": m["total_return_pct"],
                "max_drawdown_pct": m["max_drawdown_pct"],
                "trades": m["trades"],
                "params": p,
            }
        )

        if idx % 100 == 0:
            print(f"Оптимизация: {idx}/{trials}")

    res = pd.DataFrame(rows)
    res = res.sort_values(["cagr_pct", "total_return_pct"], ascending=False).reset_index(drop=True)
    return res


def print_metrics(title: str, m: dict[str, Any]) -> None:
    print(f"\n===== {title} =====")
    print(f"Период:                 {m['period_start'].date()} -> {m['period_end'].date()}")
    print(f"Начальный капитал:      {m['initial_cash']:.2f}")
    print(f"Финальный капитал:      {m['final_value']:.2f}")
    print(f"Итоговая доходность:    {m['total_return_pct']:.2f}%")
    print(f"CAGR (годовых):         {m['cagr_pct']:.2f}%")
    print(f"Max Drawdown:           {m['max_drawdown_pct']:.2f}%")
    if np.isnan(m["sharpe_ratio"]):
        print("Sharpe Ratio:           nan")
    else:
        print(f"Sharpe Ratio:           {m['sharpe_ratio']:.4f}")
    print(f"Количество сделок:      {m['trades']}")
    print(f"Win Rate:               {m['win_rate_pct']:.2f}%")
    print(f"Average Win:            {m['avg_win']:.2f}")
    print(f"Average Loss:           {m['avg_loss']:.2f}")
    print(f"Profit Factor:          {m['profit_factor']:.4f}")
    print(f"Expectancy / trade:     {m['expectancy']:.2f}")
    print("================================")


def main() -> None:
    symbol = "AMD"
    since = "2022-01-01"

    df = load_yfinance_ohlcv(symbol, since)

    base_out = apply_strategy(df)
    cfg = BacktestConfig()
    base_metrics = run_backtest(base_out, cfg)
    print_metrics("БАЗОВАЯ СТРАТЕГИЯ", base_metrics)

    opt = optimize_parameters(df, cfg)
    print("\n===== ТОП-10 ПАРАМЕТРОВ ПО CAGR =====")
    for i, row in opt.head(10).iterrows():
        p: StrategyParams = row["params"]
        print(
            f"{i+1:2d}. CAGR={row['cagr_pct']:.2f}% Ret={row['total_return_pct']:.2f}% DD={row['max_drawdown_pct']:.2f}% "
            f"Trades={int(row['trades'])} | closeLoc>{p.close_location_min:.2f} rangeMult>{p.range_multiplier:.2f} "
            f"volRatio>{p.volume_ratio_min:.2f} stopBuf={p.stop_buffer_mult:.2f} timeout={p.timeout_bars} redVol>{p.strong_red_volume_ratio_min:.2f} "
            f"RSI={'ON' if p.use_rsi_filter else 'OFF'}({p.rsi_entry_min:.0f}-{p.rsi_entry_max:.0f}) exit<{p.rsi_exit_bear:.0f} "
            f"KAMA={'ON' if p.use_kama_filter else 'OFF'} in>{p.kama_entry_buffer:.3f} out<{p.kama_exit_buffer:.3f}"
        )

    best_params: StrategyParams = opt.iloc[0]["params"]
    best_out = _apply_strategy_with_params(df, best_params)
    best_metrics = run_backtest(best_out, cfg)
    print_metrics("ЛУЧШАЯ КОМБИНАЦИЯ", best_metrics)

    if best_metrics["cagr_pct"] >= 8.0:
        print("\nЦель достигнута: CAGR >= 8%")
    else:
        print("\nЦель не достигнута: CAGR < 8%")


if __name__ == "__main__":
    main()
