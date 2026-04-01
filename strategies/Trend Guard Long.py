#!/usr/bin/env python3

from __future__ import annotations

import argparse
import itertools
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import backtrader as bt
import pandas as pd
import yfinance as yf

UTC = timezone.utc


@dataclass(slots=True)
class BacktestConfig:
    symbol: str = "AAPL"
    timeframe: str = "1d"
    since: str | None = "2024-01-01"
    till: str | None = None

    initial_cash: float = 100_000.0
    commission: float = 0.0005
    slippage: float = 0.0003

    sma_short: int = 50
    sma_long: int = 150
    roc_fast: int = 10
    roc_slow: int = 84
    trailing_stop_pct: float = 0.10
    capital_allocation: float = 1.0

    enable_exit_regime_break: bool = True
    enable_exit_trailing: bool = True
    enable_exit_two_bars_below_short: bool = True

    yfinance_chunk_days: int = 3650
    max_retries: int = 6
    retry_backoff_sec: float = 2.0
    request_pause_sec: float = 0.2

    grid_sma_short: tuple[int, ...] = (30, 50, 70)
    grid_sma_long: tuple[int, ...] = (150, 200, 250)
    grid_roc_fast: tuple[int, ...] = (10, 21, 30)
    grid_roc_slow: tuple[int, ...] = (42, 63, 84)
    grid_trailing_stop: tuple[float, ...] = (0.08, 0.10, 0.12, 0.15)
    grid_capital_allocation: tuple[float, ...] = (0.5, 0.75, 1.0)

    optimization_max_dd_pct: float = 35.0
    optimization_min_trades: int = 5

    enable_strategy_logs: bool = True


class TrendGuardLongStrategy(bt.Strategy):

    params = dict(
        sma_short=50,
        sma_long=200,
        roc_fast=21,
        roc_slow=63,
        trailing_stop_pct=0.12,
        capital_allocation=1.0,
        enable_exit_regime_break=True,
        enable_exit_trailing=True,
        enable_exit_two_bars_below_short=True,
        enable_logs=True,
    )

    def __init__(self) -> None:
        self.sma_short = bt.ind.SMA(self.data.close, period=self.p.sma_short)
        self.sma_long = bt.ind.SMA(self.data.close, period=self.p.sma_long)
        self.roc_fast = bt.ind.ROC(self.data.close, period=self.p.roc_fast)
        self.roc_slow = bt.ind.ROC(self.data.close, period=self.p.roc_slow)

        self.order: bt.Order | None = None
        self.entry_price: float | None = None
        self.highest_close_since_entry: float | None = None
        self.last_exit_reason: str = ""

        self.wait_for_regime_reset = False

    def log(self, msg: str) -> None:
        if not self.p.enable_logs:
            return
        dt = self.datas[0].datetime.datetime(0).isoformat()
        logging.info("[%s] %s", dt, msg)

    def _regime_long(self) -> bool:
        close_now = float(self.data.close[0])
        return (
            close_now > float(self.sma_long[0])
            and float(self.sma_short[0]) > float(self.sma_long[0])
            and float(self.roc_slow[0]) > 0.0
        )

    def _enough_history(self) -> bool:
        need = max(self.p.sma_short, self.p.sma_long, self.p.roc_fast + 1, self.p.roc_slow + 1) + 2
        return len(self) >= need

    def _calc_entry_size(self) -> int:
        close_now = float(self.data.close[0])
        if close_now <= 0:
            return 0

        cash = float(self.broker.getcash())
        target_cash = cash * float(self.p.capital_allocation)
        size = math.floor(target_cash / close_now)
        return max(size, 0)

    def _entry_reasons(self) -> list[str]:
        return [
            f"close({float(self.data.close[0]):.2f}) > SMA{self.p.sma_long}({float(self.sma_long[0]):.2f})",
            f"SMA{self.p.sma_short}({float(self.sma_short[0]):.2f}) > SMA{self.p.sma_long}({float(self.sma_long[0]):.2f})",
            f"ROC{self.p.roc_slow}({float(self.roc_slow[0]):.4f}) > 0",
        ]

    def _check_exit(self) -> tuple[bool, list[str]]:
        reasons: list[str] = []

        close_now = float(self.data.close[0])

        if self.p.enable_exit_regime_break:
            if close_now < float(self.sma_long[0]) and float(self.roc_fast[0]) < 0.0:
                reasons.append(
                    f"regime break: close < SMA{self.p.sma_long} и ROC{self.p.roc_fast} < 0"
                )

        if self.p.enable_exit_trailing and self.highest_close_since_entry is not None:
            trail_level = self.highest_close_since_entry * (1.0 - float(self.p.trailing_stop_pct))
            if close_now <= trail_level:
                reasons.append(
                    f"trailing stop {self.p.trailing_stop_pct*100:.1f}%: close({close_now:.2f}) <= {trail_level:.2f}"
                )

        if self.p.enable_exit_two_bars_below_short and len(self) > 1:
            c0 = float(self.data.close[0]) < float(self.sma_short[0])
            c1 = float(self.data.close[-1]) < float(self.sma_short[-1])
            if c0 and c1:
                reasons.append(f"2 бара подряд ниже SMA{self.p.sma_short}")

        return len(reasons) > 0, reasons

    def notify_order(self, order: bt.Order) -> None:
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        if order.status == bt.Order.Completed:
            if order.isbuy():
                self.entry_price = float(order.executed.price)
                self.highest_close_since_entry = float(self.data.close[0])
                self.log(
                    f"ENTRY FILLED: size={order.executed.size:.4f} price={order.executed.price:.2f}"
                )
            else:
                self.log(
                    f"EXIT FILLED: size={order.executed.size:.4f} price={order.executed.price:.2f} reason={self.last_exit_reason}"
                )
                self.entry_price = None
                self.highest_close_since_entry = None
                self.wait_for_regime_reset = True
                self.last_exit_reason = ""

            self.order = None
            return

        if order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.log(f"ORDER {order.ref} {order.getstatusname()}")
            self.order = None

    def notify_trade(self, trade: bt.Trade) -> None:
        if trade.isclosed:
            self.log(f"TRADE CLOSED: gross={trade.pnl:.2f}, net={trade.pnlcomm:.2f}")

    def next(self) -> None:
        if self.order is not None:
            return

        if not self._enough_history():
            return

        regime = self._regime_long()

        if self.wait_for_regime_reset and not regime:
            self.wait_for_regime_reset = False
            self.log("RE-ENTRY ARMED: режим long снова может быть пойман")

        if self.position.size > 0:
            close_now = float(self.data.close[0])
            if self.highest_close_since_entry is None:
                self.highest_close_since_entry = close_now
            else:
                self.highest_close_since_entry = max(self.highest_close_since_entry, close_now)

            should_exit, reasons = self._check_exit()
            if should_exit:
                self.last_exit_reason = "; ".join(reasons)
                self.log("EXIT SIGNAL: " + self.last_exit_reason)
                self.order = self.close()
            return

        if regime and not self.wait_for_regime_reset:
            size = self._calc_entry_size()
            if size < 1:
                self.log("ENTRY SKIP: размер позиции < 1")
                return

            self.log("ENTRY SIGNAL: " + " | ".join(self._entry_reasons()))
            self.order = self.buy(size=size)


def parse_dt(value: str | None) -> datetime:
    if value is None:
        return datetime.now(tz=UTC)

    raw = value.strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=UTC)


def timeframe_to_yf_interval(timeframe: str) -> str:
    mapping = {
        "1d": "1d",
        "1wk": "1wk",
        "1mo": "1mo",
    }
    if timeframe not in mapping:
        raise ValueError(f"Неподдерживаемый timeframe={timeframe}. Для этой стратегии используйте 1d/1wk/1mo")
    return mapping[timeframe]


def timeframe_to_timedelta(timeframe: str) -> timedelta:
    mapping = {
        "1d": timedelta(days=1),
        "1wk": timedelta(days=7),
        "1mo": timedelta(days=31),
    }
    if timeframe not in mapping:
        raise ValueError(f"Нет timedelta mapping для timeframe={timeframe}")
    return mapping[timeframe]


def normalize_yf_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [c[0] for c in out.columns]

    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise RuntimeError(f"В ответе yfinance нет обязательных колонок: {missing}")

    out = out[required].copy()
    out = out.dropna(subset=required)

    if out.empty:
        return out

    if out.index.tz is None:
        out.index = out.index.tz_localize(UTC)
    else:
        out.index = out.index.tz_convert(UTC)

    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]

    out.columns = ["open", "high", "low", "close", "volume"]
    out = out.astype(float)
    return out


def fetch_ohlcv_yfinance_paginated(
    symbol: str,
    timeframe: str,
    since: str | None,
    till: str | None,
    chunk_days: int,
    max_retries: int,
    retry_backoff_sec: float,
    request_pause_sec: float,
) -> pd.DataFrame:
    interval = timeframe_to_yf_interval(timeframe)

    since_dt = parse_dt(since)
    till_dt = parse_dt(till) if till is not None else datetime.now(tz=UTC)

    if since_dt >= till_dt:
        raise ValueError("since должен быть раньше till")

    logging.info(
        "Старт загрузки yfinance: symbol=%s interval=%s from=%s till=%s chunk_days=%s",
        symbol,
        interval,
        since_dt.isoformat(),
        till_dt.isoformat(),
        chunk_days,
    )

    chunks: list[pd.DataFrame] = []
    start_dt = since_dt
    page = 0

    while start_dt < till_dt:
        page += 1
        end_dt = min(start_dt + timedelta(days=chunk_days), till_dt)

        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")

        chunk_df: pd.DataFrame | None = None

        for attempt in range(1, max_retries + 1):
            try:
                raw = yf.download(
                    tickers=symbol,
                    start=start_str,
                    end=end_str,
                    interval=interval,
                    auto_adjust=False,
                    progress=False,
                    threads=False,
                )
                chunk_df = normalize_yf_columns(raw)
                if chunk_df.empty:
                    raise RuntimeError("Пустой ответ yfinance для чанка")
                break
            except Exception as exc:
                wait_s = min(retry_backoff_sec * (2 ** (attempt - 1)), 30.0)
                logging.warning(
                    "Ошибка yfinance (%s), page=%s attempt=%s/%s sleep=%.1fs",
                    exc,
                    page,
                    attempt,
                    max_retries,
                    wait_s,
                )
                time.sleep(wait_s)

        if chunk_df is None:
            raise RuntimeError(f"Не удалось загрузить chunk page={page} после всех попыток")

        chunks.append(chunk_df)
        logging.info("Загружен chunk page=%s, bars=%s", page, len(chunk_df))

        start_dt = end_dt
        if request_pause_sec > 0:
            time.sleep(request_pause_sec)

    if not chunks:
        raise ValueError("Получены пустые OHLCV-данные из yfinance")

    df = pd.concat(chunks, axis=0)
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]

    df = df[(df.index >= since_dt) & (df.index <= till_dt)]
    if df.empty:
        raise ValueError("После объединения chunks данные пусты")

    tf_delta = timeframe_to_timedelta(timeframe)
    now_utc = datetime.now(tz=UTC)
    if len(df) > 0 and (df.index[-1].to_pydatetime() + tf_delta) > now_utc:
        df = df.iloc[:-1]

    if df.empty:
        raise ValueError("После удаления незакрытой свечи данные пусты")

    logging.info("Загрузка yfinance завершена: bars=%s", len(df))
    return df


def safe_get(dct: dict[str, Any], path: list[str], default: Any = None) -> Any:
    cur: Any = dct
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def collect_metrics(
    strat: TrendGuardLongStrategy,
    initial_cash: float,
    df: pd.DataFrame,
) -> dict[str, Any]:
    final_value = float(strat.broker.getvalue())
    total_return_pct = (final_value / initial_cash - 1.0) * 100.0

    years = max((df.index[-1] - df.index[0]).days / 365.25, 1e-9)
    cagr_pct = ((final_value / initial_cash) ** (1.0 / years) - 1.0) * 100.0

    dd_analysis = strat.analyzers.drawdown.get_analysis()
    sharpe_analysis = strat.analyzers.sharpe.get_analysis()
    trade_analysis = strat.analyzers.trades.get_analysis()

    max_drawdown_pct = float(safe_get(dd_analysis, ["max", "drawdown"], 0.0) or 0.0)

    sharpe_ratio = safe_get(sharpe_analysis, ["sharperatio"], None)
    sharpe_ratio = (
        float(sharpe_ratio)
        if sharpe_ratio is not None and not math.isnan(sharpe_ratio)
        else float("nan")
    )

    total_closed = int(safe_get(trade_analysis, ["total", "closed"], 0) or 0)
    won_total = int(safe_get(trade_analysis, ["won", "total"], 0) or 0)
    lost_total = int(safe_get(trade_analysis, ["lost", "total"], 0) or 0)

    win_rate_pct = (won_total / total_closed * 100.0) if total_closed > 0 else 0.0

    gross_profit = float(safe_get(trade_analysis, ["won", "pnl", "total"], 0.0) or 0.0)
    gross_loss_abs = abs(float(safe_get(trade_analysis, ["lost", "pnl", "total"], 0.0) or 0.0))
    profit_factor = (gross_profit / gross_loss_abs) if gross_loss_abs > 0 else float("inf")

    avg_win = float(safe_get(trade_analysis, ["won", "pnl", "average"], 0.0) or 0.0)
    avg_loss = float(safe_get(trade_analysis, ["lost", "pnl", "average"], 0.0) or 0.0)

    if total_closed > 0:
        win_prob = won_total / total_closed
        loss_prob = lost_total / total_closed
        expectancy = win_prob * avg_win + loss_prob * avg_loss
    else:
        expectancy = 0.0

    return {
        "period_start": df.index[0].to_pydatetime(),
        "period_end": df.index[-1].to_pydatetime(),
        "period_years": years,
        "initial_cash": initial_cash,
        "final_value": final_value,
        "total_return_pct": total_return_pct,
        "cagr_pct": cagr_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "sharpe_ratio": sharpe_ratio,
        "total_trades": total_closed,
        "wins": won_total,
        "losses": lost_total,
        "win_rate_pct": win_rate_pct,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
    }


def run_backtest(
    cfg: BacktestConfig,
    df: pd.DataFrame | None = None,
    overrides: dict[str, Any] | None = None,
    enable_logs: bool | None = None,
) -> dict[str, Any]:
    if df is None:
        df = fetch_ohlcv_yfinance_paginated(
            symbol=cfg.symbol,
            timeframe=cfg.timeframe,
            since=cfg.since,
            till=cfg.till,
            chunk_days=cfg.yfinance_chunk_days,
            max_retries=cfg.max_retries,
            retry_backoff_sec=cfg.retry_backoff_sec,
            request_pause_sec=cfg.request_pause_sec,
        )

    params = {
        "sma_short": cfg.sma_short,
        "sma_long": cfg.sma_long,
        "roc_fast": cfg.roc_fast,
        "roc_slow": cfg.roc_slow,
        "trailing_stop_pct": cfg.trailing_stop_pct,
        "capital_allocation": cfg.capital_allocation,
        "enable_exit_regime_break": cfg.enable_exit_regime_break,
        "enable_exit_trailing": cfg.enable_exit_trailing,
        "enable_exit_two_bars_below_short": cfg.enable_exit_two_bars_below_short,
        "enable_logs": cfg.enable_strategy_logs if enable_logs is None else enable_logs,
    }
    if overrides:
        params.update(overrides)

    data_feed = bt.feeds.PandasData(dataname=df)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(cfg.initial_cash)
    cerebro.broker.setcommission(commission=cfg.commission)
    cerebro.broker.set_slippage_perc(perc=cfg.slippage)

    cerebro.addstrategy(TrendGuardLongStrategy, **params)

    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio_A, _name="sharpe", riskfreerate=0.0, annualize=True)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    result = cerebro.run()[0]
    metrics = collect_metrics(result, cfg.initial_cash, df)
    metrics["strategy_params"] = params
    return metrics


def run_optimization(cfg: BacktestConfig, df: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    combos = list(
        itertools.product(
            cfg.grid_sma_short,
            cfg.grid_sma_long,
            cfg.grid_roc_fast,
            cfg.grid_roc_slow,
            cfg.grid_trailing_stop,
            cfg.grid_capital_allocation,
        )
    )

    rows: list[dict[str, Any]] = []
    logging.info("Optimization started: %s combinations", len(combos))

    for idx, (sma_s, sma_l, roc_f, roc_s, tr_stop, cap_alloc) in enumerate(combos, start=1):
        if sma_s >= sma_l:
            continue

        overrides = {
            "sma_short": int(sma_s),
            "sma_long": int(sma_l),
            "roc_fast": int(roc_f),
            "roc_slow": int(roc_s),
            "trailing_stop_pct": float(tr_stop),
            "capital_allocation": float(cap_alloc),
        }

        m = run_backtest(cfg=cfg, df=df, overrides=overrides, enable_logs=False)

        row = {
            "sma_short": int(sma_s),
            "sma_long": int(sma_l),
            "roc_fast": int(roc_f),
            "roc_slow": int(roc_s),
            "trailing_stop_pct": float(tr_stop),
            "capital_allocation": float(cap_alloc),
            "cagr_pct": float(m["cagr_pct"]),
            "total_return_pct": float(m["total_return_pct"]),
            "max_drawdown_pct": float(m["max_drawdown_pct"]),
            "sharpe_ratio": float(m["sharpe_ratio"]) if not math.isnan(float(m["sharpe_ratio"])) else float("nan"),
            "total_trades": int(m["total_trades"]),
            "win_rate_pct": float(m["win_rate_pct"]),
            "profit_factor": float(m["profit_factor"]),
            "expectancy": float(m["expectancy"]),
        }
        rows.append(row)

        logging.info(
            "Opt %s/%s | SMA(%s/%s) ROC(%s/%s) trail=%.2f alloc=%.2f => CAGR=%.2f%% DD=%.2f%% trades=%s",
            idx,
            len(combos),
            sma_s,
            sma_l,
            roc_f,
            roc_s,
            tr_stop,
            cap_alloc,
            row["cagr_pct"],
            row["max_drawdown_pct"],
            row["total_trades"],
        )

    all_sorted = sorted(
        rows,
        key=lambda r: (r["cagr_pct"], r["total_return_pct"], -r["max_drawdown_pct"]),
        reverse=True,
    )

    filtered = [
        r
        for r in rows
        if r["max_drawdown_pct"] <= cfg.optimization_max_dd_pct and r["total_trades"] >= cfg.optimization_min_trades
    ]
    filtered_sorted = sorted(
        filtered,
        key=lambda r: (r["cagr_pct"], r["total_return_pct"], -r["max_drawdown_pct"]),
        reverse=True,
    )

    return all_sorted, filtered_sorted


def print_top20(rows: list[dict[str, Any]], title: str) -> None:
    print(f"\n===== {title} =====")
    if not rows:
        print("Нет результатов")
        print("===============================\n")
        return

    for i, r in enumerate(rows[:20], start=1):
        sharpe_val = r["sharpe_ratio"]
        sharpe_str = f"{sharpe_val:.3f}" if not math.isnan(sharpe_val) else "nan"
        print(
            f"{i:2d}. SMA={r['sma_short']:>3d}/{r['sma_long']:>3d} | ROC={r['roc_fast']:>2d}/{r['roc_slow']:>2d} | "
            f"TRAIL={r['trailing_stop_pct']*100:>4.1f}% | ALLOC={r['capital_allocation']:.2f} | "
            f"CAGR={r['cagr_pct']:>6.2f}% | Ret={r['total_return_pct']:>7.2f}% | DD={r['max_drawdown_pct']:>6.2f}% | "
            f"Sharpe={sharpe_str:>6} | Trades={r['total_trades']:>3d} | WR={r['win_rate_pct']:>6.2f}% | PF={r['profit_factor']:>6.3f}"
        )

    print("===============================\n")


def print_metrics(metrics: dict[str, Any], cfg: BacktestConfig) -> None:
    print("\n===== РЕЗУЛЬТАТЫ BACKTEST =====")
    print("Стратегия:              Trend Guard Long")
    print("Источник данных:        yfinance")
    print(f"Инструмент:             {cfg.symbol}")
    print(f"Таймфрейм:              {cfg.timeframe}")
    print(f"Период:                 {metrics['period_start'].date()} -> {metrics['period_end'].date()} ({metrics['period_years']:.2f} лет)")
    print(f"Начальный капитал:      {metrics['initial_cash']:.2f}")
    print(f"Финальный капитал:      {metrics['final_value']:.2f}")
    print(f"Итоговая доходность:    {metrics['total_return_pct']:.2f}%")
    print(f"CAGR (годовых):         {metrics['cagr_pct']:.2f}%")
    print(f"Max Drawdown:           {metrics['max_drawdown_pct']:.2f}%")

    sharpe = metrics["sharpe_ratio"]
    sharpe_str = f"{sharpe:.4f}" if not math.isnan(sharpe) else "nan"
    print(f"Sharpe Ratio:           {sharpe_str}")

    print(f"Количество сделок:      {int(metrics['total_trades'])}")
    print(f"Win Rate:               {metrics['win_rate_pct']:.2f}%")
    print(f"Average Win:            {metrics['avg_win']:.2f}")
    print(f"Average Loss:           {metrics['avg_loss']:.2f}")
    print(f"Profit Factor:          {metrics['profit_factor']:.4f}")
    print(f"Expectancy / trade:     {metrics['expectancy']:.2f}")
    print("================================\n")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="AAPL 1d long-only regime strategy")

    p.add_argument("--symbol", type=str, default="AAPL")
    p.add_argument("--timeframe", type=str, default="1d")
    p.add_argument("--since", type=str, default="2024-01-01")
    p.add_argument("--till", type=str, default=None)

    p.add_argument("--initial-cash", type=float, default=100_000.0)
    p.add_argument("--commission", type=float, default=0.0005)
    p.add_argument("--slippage", type=float, default=0.0003)

    p.add_argument("--sma-short", type=int, default=50)
    p.add_argument("--sma-long", type=int, default=150)
    p.add_argument("--roc-fast", type=int, default=10)
    p.add_argument("--roc-slow", type=int, default=84)
    p.add_argument("--trailing-stop-pct", type=float, default=0.10)
    p.add_argument("--capital-allocation", type=float, default=1.0)

    p.add_argument("--disable-exit-regime-break", action="store_true")
    p.add_argument("--disable-exit-trailing", action="store_true")
    p.add_argument("--disable-exit-two-bars", action="store_true")

    p.add_argument("--yfinance-chunk-days", type=int, default=3650)
    p.add_argument("--max-retries", type=int, default=6)
    p.add_argument("--retry-backoff-sec", type=float, default=2.0)
    p.add_argument("--request-pause-sec", type=float, default=0.2)

    p.add_argument("--skip-optimization", action="store_true")
    p.add_argument("--enable-strategy-logs", action="store_true")
    p.add_argument("--log-level", type=str, default="INFO")

    return p


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    cfg = BacktestConfig(
        symbol=args.symbol.upper(),
        timeframe=args.timeframe,
        since=args.since,
        till=args.till,
        initial_cash=args.initial_cash,
        commission=args.commission,
        slippage=args.slippage,
        sma_short=args.sma_short,
        sma_long=args.sma_long,
        roc_fast=args.roc_fast,
        roc_slow=args.roc_slow,
        trailing_stop_pct=args.trailing_stop_pct,
        capital_allocation=args.capital_allocation,
        enable_exit_regime_break=not args.disable_exit_regime_break,
        enable_exit_trailing=not args.disable_exit_trailing,
        enable_exit_two_bars_below_short=not args.disable_exit_two_bars,
        yfinance_chunk_days=args.yfinance_chunk_days,
        max_retries=args.max_retries,
        retry_backoff_sec=args.retry_backoff_sec,
        request_pause_sec=args.request_pause_sec,
        enable_strategy_logs=args.enable_strategy_logs,
    )

    if cfg.sma_short <= 0 or cfg.sma_long <= 0:
        raise SystemExit("Ошибка: SMA периоды должны быть > 0")
    if cfg.sma_short >= cfg.sma_long:
        raise SystemExit("Ошибка: sma_short должен быть меньше sma_long")
    if cfg.roc_fast <= 0 or cfg.roc_slow <= 0:
        raise SystemExit("Ошибка: ROC периоды должны быть > 0")
    if cfg.trailing_stop_pct <= 0 or cfg.trailing_stop_pct >= 1:
        raise SystemExit("Ошибка: trailing_stop_pct должен быть в диапазоне (0, 1)")
    if cfg.capital_allocation <= 0 or cfg.capital_allocation > 1:
        raise SystemExit("Ошибка: capital_allocation должен быть в диапазоне (0, 1]")

    try:
        df = fetch_ohlcv_yfinance_paginated(
            symbol=cfg.symbol,
            timeframe=cfg.timeframe,
            since=cfg.since,
            till=cfg.till,
            chunk_days=cfg.yfinance_chunk_days,
            max_retries=cfg.max_retries,
            retry_backoff_sec=cfg.retry_backoff_sec,
            request_pause_sec=cfg.request_pause_sec,
        )

        if args.skip_optimization:
            metrics = run_backtest(cfg=cfg, df=df, enable_logs=cfg.enable_strategy_logs)
            print_metrics(metrics, cfg)
            return

        all_sorted, filtered_sorted = run_optimization(cfg=cfg, df=df)

        print_top20(all_sorted, "TOP-20 КОМБИНАЦИЙ ПО CAGR (без ограничений)")
        print_top20(
            filtered_sorted,
            f"TOP-20 КОМБИНАЦИЙ ПО CAGR (DD <= {cfg.optimization_max_dd_pct:.1f}% и trades >= {cfg.optimization_min_trades})",
        )

        if filtered_sorted:
            best = filtered_sorted[0]
            print(
                "Выбрана лучшая комбинация по CAGR при ограничениях: "
                f"SMA={best['sma_short']}/{best['sma_long']} ROC={best['roc_fast']}/{best['roc_slow']} "
                f"TRAIL={best['trailing_stop_pct']*100:.1f}% ALLOC={best['capital_allocation']:.2f}"
            )
        else:
            best = all_sorted[0]
            print("Комбинации с ограничениями не найдены, выбрана лучшая по CAGR без ограничений.")

        overrides = {
            "sma_short": best["sma_short"],
            "sma_long": best["sma_long"],
            "roc_fast": best["roc_fast"],
            "roc_slow": best["roc_slow"],
            "trailing_stop_pct": best["trailing_stop_pct"],
            "capital_allocation": best["capital_allocation"],
        }

        metrics = run_backtest(cfg=cfg, df=df, overrides=overrides, enable_logs=cfg.enable_strategy_logs)
        print_metrics(metrics, cfg)

    except KeyboardInterrupt:
        logging.error("Выполнение остановлено пользователем")
        raise SystemExit(130) from None
    except Exception as exc:
        logging.exception("Ошибка выполнения backtest: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
