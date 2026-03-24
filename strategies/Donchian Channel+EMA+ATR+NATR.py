#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Donchian Breakout стратегия, адаптированная под акции MOEX.

Логика:
- EMA как фильтр глобального тренда
- Вход: пробой верхнего Donchian-канала (без lookahead)
- Выход: пробой нижнего Donchian-канала или ATR-стоп/ATR-тейк
- Риск-менеджмент: риск на сделку + ограничение доли капитала

Источник данных: ISS API Московской биржи (MOEX).
"""

from __future__ import annotations

import argparse
import logging
import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import backtrader as bt
import pandas as pd
import requests


MOSCOW_TZ = ZoneInfo("Europe/Moscow")


# ----------------------------- Конфигурация ----------------------------- #

@dataclass(slots=True)
class BacktestConfig:
    symbol: str = "GAZP"
    timeframe: str = "1h"
    since: str | int | None = "2025-01-01"
    till: str | None = None
    initial_cash: float = 100_000.0
    commission: float = 0.0005      # 0.05%
    slippage: float = 0.0003        # 0.03%

    moex_engine: str = "stock"
    moex_market: str = "shares"
    moex_board: str = "TQBR"

    ema_period: int = 220
    donchian_entry_period: int = 70
    donchian_exit_period: int = 15
    atr_period: int = 14
    atr_stop_mult: float = 2.0
    atr_take_mult: float = 6.0

    require_ema_slope_up: bool = False
    ema_slope_period: int = 10
    breakout_atr_buffer: float = 0.0
    natr_min: float = 0.0

    risk_per_trade: float = 0.01
    max_capital_pct: float = 1.0

    page_size: int = 500
    max_retries: int = 7
    progress_every_pages: int = 10
    enable_strategy_logs: bool = False


# ----------------------------- Индикаторы ----------------------------- #

class NATR(bt.Indicator):
    """Normalized ATR = ATR / Close * 100."""

    lines = ("natr",)
    params = dict(period=14)

    def __init__(self) -> None:
        atr = bt.ind.ATR(self.data, period=self.p.period)
        self.lines.natr = (atr / self.data.close) * 100.0


# ----------------------------- Стратегия ----------------------------- #

class DonchianBreakoutStrategy(bt.Strategy):
    params = dict(
        ema_period=220,
        donchian_entry_period=70,
        donchian_exit_period=15,
        atr_period=14,
        atr_stop_mult=2.0,
        atr_take_mult=6.0,
        require_ema_slope_up=False,
        ema_slope_period=10,
        breakout_atr_buffer=0.0,
        natr_min=0.0,
        risk_per_trade=0.01,
        max_capital_pct=1.0,
        enable_logs=False,
    )

    def __init__(self) -> None:
        self.ema = bt.ind.EMA(self.data.close, period=self.p.ema_period)
        self.atr = bt.ind.ATR(self.data, period=self.p.atr_period)
        self.natr = NATR(self.data, period=self.p.atr_period)

        # Используем только завершенные бары в расчете каналов (без lookahead).
        self.donchian_entry_high = bt.ind.Highest(
            self.data.high(-1),
            period=self.p.donchian_entry_period,
        )
        self.donchian_exit_low = bt.ind.Lowest(
            self.data.low(-1),
            period=self.p.donchian_exit_period,
        )

        self.entry_order: bt.Order | None = None
        self.stop_order: bt.Order | None = None
        self.take_order: bt.Order | None = None
        self.manual_exit_order: bt.Order | None = None

    def log(self, msg: str) -> None:
        if not self.p.enable_logs:
            return
        dt = self.datas[0].datetime.datetime(0).isoformat()
        logging.info("[%s] %s", dt, msg)

    def has_pending_orders(self) -> bool:
        orders = [self.entry_order, self.stop_order, self.take_order, self.manual_exit_order]
        return any(o is not None and o.alive() for o in orders)

    def cancel_protective_orders(self) -> None:
        for order in (self.stop_order, self.take_order):
            if order is not None and order.alive():
                self.cancel(order)
        self.stop_order = None
        self.take_order = None

    def long_entry_signal(self) -> bool:
        if self.data.close[0] <= self.ema[0]:
            return False

        if self.p.require_ema_slope_up:
            if len(self) <= self.p.ema_slope_period:
                return False
            if self.ema[0] <= self.ema[-self.p.ema_slope_period]:
                return False

        if self.natr[0] < self.p.natr_min:
            return False

        breakout_level = self.donchian_entry_high[0] + self.atr[0] * self.p.breakout_atr_buffer
        return self.data.close[0] > breakout_level

    def notify_order(self, order: bt.Order) -> None:
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        if order.status == bt.Order.Completed:
            side = "BUY" if order.isbuy() else "SELL"
            self.log(
                f"ORDER FILLED: {side} size={order.executed.size:.4f} "
                f"price={order.executed.price:.2f} value={order.executed.value:.2f} "
                f"comm={order.executed.comm:.4f}"
            )

            if order is self.stop_order:
                self.log("EXIT: сработал stop-loss")
                self.entry_order = None
                self.stop_order = None
                self.take_order = None
                self.manual_exit_order = None
            elif order is self.take_order:
                self.log("EXIT: сработал take-profit")
                self.entry_order = None
                self.stop_order = None
                self.take_order = None
                self.manual_exit_order = None
            elif order is self.manual_exit_order:
                self.log("EXIT: выход по Donchian")
                self.entry_order = None
                self.stop_order = None
                self.take_order = None
                self.manual_exit_order = None
            elif order is self.entry_order:
                self.log("ENTRY: long позиция открыта")

        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.log(f"ORDER {order.ref} {order.getstatusname()}")
            if order is self.entry_order:
                self.entry_order = None
            if order is self.stop_order:
                self.stop_order = None
            if order is self.take_order:
                self.take_order = None
            if order is self.manual_exit_order:
                self.manual_exit_order = None

    def notify_trade(self, trade: bt.Trade) -> None:
        if trade.isclosed:
            self.log(f"TRADE CLOSED: gross={trade.pnl:.2f} net={trade.pnlcomm:.2f}")

    def next(self) -> None:
        if self.has_pending_orders():
            return

        # Блок управления открытой long-позицией вынесен отдельно,
        # чтобы потом было проще добавить short-логику симметрично.
        if self.position.size > 0:
            if self.data.close[0] < self.donchian_exit_low[0]:
                self.log(
                    f"EXIT SIGNAL: close={self.data.close[0]:.2f}, "
                    f"donchian_exit_low={self.donchian_exit_low[0]:.2f}"
                )
                self.cancel_protective_orders()
                self.manual_exit_order = self.close()
            return

        if self.long_entry_signal():
            atr = float(self.atr[0])
            close = float(self.data.close[0])

            if atr <= 0 or close <= 0:
                return

            stop_dist = self.p.atr_stop_mult * atr
            stop_price = close - stop_dist
            take_price = close + self.p.atr_take_mult * atr

            if stop_price <= 0:
                return

            equity = float(self.broker.getvalue())
            cash = float(self.broker.getcash())

            risk_cash = equity * self.p.risk_per_trade
            size_by_risk = risk_cash / stop_dist
            size_by_capital = (cash * self.p.max_capital_pct) / close
            size = min(size_by_risk, size_by_capital)

            if size <= 0:
                return

            self.log(
                f"LONG SIGNAL: close={close:.2f}, ema={self.ema[0]:.2f}, "
                f"donchian_entry={self.donchian_entry_high[0]:.2f}, atr={atr:.2f}, "
                f"natr={self.natr[0]:.2f}, size={size:.4f}"
            )

            bracket = self.buy_bracket(
                size=size,
                exectype=bt.Order.Market,
                stopprice=stop_price,
                stopexec=bt.Order.Stop,
                limitprice=take_price,
                limitexec=bt.Order.Limit,
            )
            self.entry_order, self.stop_order, self.take_order = bracket


# ----------------------------- Загрузка MOEX данных ----------------------------- #

def parse_date(value: str | int | None) -> date:
    if value is None:
        return datetime.now(MOSCOW_TZ).date()

    if isinstance(value, int):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).astimezone(MOSCOW_TZ).date()

    raw = value.strip()
    if raw.isdigit():
        return datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc).astimezone(MOSCOW_TZ).date()

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(MOSCOW_TZ).date()
    except ValueError:
        return datetime.strptime(raw, "%Y-%m-%d").date()


def timeframe_to_moex_interval(timeframe: str) -> int:
    mapping = {
        "1m": 1,
        "10m": 10,
        "1h": 60,
        "1d": 24,
        "1w": 7,
        "1M": 31,
    }
    if timeframe not in mapping:
        raise ValueError(
            f"Таймфрейм {timeframe} не поддерживается MOEX. Используйте: {', '.join(mapping)}"
        )
    return mapping[timeframe]


def fetch_moex_candles_paginated(
    symbol: str,
    timeframe: str,
    since: str | int | None,
    till: str | int | None,
    engine: str,
    market: str,
    board: str,
    page_size: int = 500,
    max_retries: int = 7,
    progress_every_pages: int = 10,
) -> pd.DataFrame:
    interval = timeframe_to_moex_interval(timeframe)
    date_from = parse_date(since)
    date_till = parse_date(till) if till is not None else datetime.now(MOSCOW_TZ).date()

    if date_from > date_till:
        raise ValueError("Параметр since не может быть позже till")

    url = (
        f"https://iss.moex.com/iss/engines/{engine}/markets/{market}/boards/{board}/"
        f"securities/{symbol}/candles.json"
    )

    all_rows: list[list[Any]] = []
    start = 0
    pages = 0

    logging.info(
        "Старт загрузки MOEX: symbol=%s board=%s timeframe=%s from=%s till=%s",
        symbol,
        board,
        timeframe,
        date_from,
        date_till,
    )

    while True:
        params = {
            "from": date_from.isoformat(),
            "till": date_till.isoformat(),
            "interval": interval,
            "start": start,
        }

        payload: dict[str, Any] | None = None
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.get(url, params=params, timeout=25)
                response.raise_for_status()
                payload = response.json()
                break
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                wait_s = min(2 ** attempt, 30)
                logging.warning(
                    "Временная ошибка MOEX API (%s). Повтор %s/%s через %ss",
                    exc,
                    attempt,
                    max_retries,
                    wait_s,
                )
                time.sleep(wait_s)

        if payload is None:
            raise RuntimeError("Не удалось получить данные MOEX после всех повторов")

        candles = payload.get("candles", {})
        columns = candles.get("columns", [])
        data = candles.get("data", [])

        if not columns:
            raise RuntimeError("MOEX API вернул пустую структуру columns")

        if not data:
            break

        all_rows.extend(data)
        pages += 1

        if progress_every_pages > 0 and pages % progress_every_pages == 0:
            logging.info("Загружено страниц MOEX: %s, свечей: %s", pages, len(all_rows))

        start += len(data)
        if len(data) < page_size:
            break

    if not all_rows:
        raise ValueError("MOEX вернул пустые данные по выбранным параметрам")

    df = pd.DataFrame(all_rows, columns=columns)

    required = {"open", "high", "low", "close", "volume", "begin", "end"}
    if not required.issubset(set(df.columns)):
        raise RuntimeError(
            f"MOEX API вернул неожиданные колонки. Нужны {sorted(required)}, получили {list(df.columns)}"
        )

    df = df.dropna(subset=["open", "high", "low", "close", "volume", "begin", "end"]).copy()
    if df.empty:
        raise ValueError("После очистки от пустых значений данные MOEX пусты")

    begin_dt = pd.to_datetime(df["begin"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    end_dt = pd.to_datetime(df["end"], format="%Y-%m-%d %H:%M:%S", errors="coerce")

    df = df.loc[begin_dt.notna() & end_dt.notna()].copy()
    begin_dt = begin_dt.loc[df.index]
    end_dt = end_dt.loc[df.index]

    begin_utc = begin_dt.dt.tz_localize(MOSCOW_TZ).dt.tz_convert(timezone.utc)
    end_utc = end_dt.dt.tz_localize(MOSCOW_TZ).dt.tz_convert(timezone.utc)

    # Исключаем потенциально незакрытую последнюю свечу.
    now_utc = datetime.now(timezone.utc)
    df = df.loc[end_utc <= now_utc].copy()
    begin_utc = begin_utc.loc[df.index]

    if df.empty:
        raise ValueError("После удаления незакрытой свечи данные MOEX пусты")

    out = df[["open", "high", "low", "close", "volume"]].astype(float).copy()
    out.index = begin_utc.to_numpy()
    out = out[~out.index.duplicated(keep="last")].sort_index()

    if out.empty:
        raise ValueError("Итоговый DataFrame после обработки пуст")

    logging.info("Загрузка MOEX завершена: страниц=%s, свечей=%s", pages, len(out))
    return out


# ----------------------------- Метрики ----------------------------- #

def safe_get(dct: dict[str, Any], path: list[str], default: Any = None) -> Any:
    cur: Any = dct
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def collect_metrics(
    strat: DonchianBreakoutStrategy,
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
    win_rate = (won_total / total_closed * 100.0) if total_closed > 0 else 0.0

    gross_profit = float(safe_get(trade_analysis, ["won", "pnl", "total"], 0.0) or 0.0)
    gross_loss_abs = abs(float(safe_get(trade_analysis, ["lost", "pnl", "total"], 0.0) or 0.0))
    profit_factor = (gross_profit / gross_loss_abs) if gross_loss_abs > 0 else float("inf")

    buy_hold_return_pct = (float(df["close"].iloc[-1]) / float(df["close"].iloc[0]) - 1.0) * 100.0

    return {
        "initial_cash": initial_cash,
        "final_value": final_value,
        "total_return_pct": total_return_pct,
        "cagr_pct": cagr_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "sharpe_ratio": sharpe_ratio,
        "total_trades": total_closed,
        "wins": won_total,
        "losses": lost_total,
        "win_rate_pct": win_rate,
        "profit_factor": profit_factor,
        "buy_hold_return_pct": buy_hold_return_pct,
    }


# ----------------------------- Вывод ----------------------------- #

def print_metrics(metrics: dict[str, Any], cfg: BacktestConfig) -> None:
    print("\n===== РЕЗУЛЬТАТЫ BACKTEST =====")
    print(f"Источник данных:         MOEX ({cfg.moex_engine}/{cfg.moex_market}/{cfg.moex_board})")
    print(f"Инструмент:             {cfg.symbol}")
    print(f"Таймфрейм:              {cfg.timeframe}")
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
    print(f"Profit Factor:          {metrics['profit_factor']:.4f}")
    print(f"Buy & Hold доходность:  {metrics['buy_hold_return_pct']:.2f}%")
    print("================================\n")


# ----------------------------- Запуск ----------------------------- #

def run_backtest(cfg: BacktestConfig) -> dict[str, Any]:
    df = fetch_moex_candles_paginated(
        symbol=cfg.symbol,
        timeframe=cfg.timeframe,
        since=cfg.since,
        till=cfg.till,
        engine=cfg.moex_engine,
        market=cfg.moex_market,
        board=cfg.moex_board,
        page_size=cfg.page_size,
        max_retries=cfg.max_retries,
        progress_every_pages=cfg.progress_every_pages,
    )

    data_feed = bt.feeds.PandasData(dataname=df)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(cfg.initial_cash)
    cerebro.broker.setcommission(commission=cfg.commission)
    cerebro.broker.set_slippage_perc(perc=cfg.slippage)

    cerebro.addstrategy(
        DonchianBreakoutStrategy,
        ema_period=cfg.ema_period,
        donchian_entry_period=cfg.donchian_entry_period,
        donchian_exit_period=cfg.donchian_exit_period,
        atr_period=cfg.atr_period,
        atr_stop_mult=cfg.atr_stop_mult,
        atr_take_mult=cfg.atr_take_mult,
        require_ema_slope_up=cfg.require_ema_slope_up,
        ema_slope_period=cfg.ema_slope_period,
        breakout_atr_buffer=cfg.breakout_atr_buffer,
        natr_min=cfg.natr_min,
        risk_per_trade=cfg.risk_per_trade,
        max_capital_pct=cfg.max_capital_pct,
        enable_logs=cfg.enable_strategy_logs,
    )

    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(
        bt.analyzers.SharpeRatio_A,
        _name="sharpe",
        riskfreerate=0.0,
        annualize=True,
    )
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    results = cerebro.run()
    strat = results[0]

    return collect_metrics(strat, cfg.initial_cash, df)


# ----------------------------- CLI ----------------------------- #

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Donchian Breakout стратегия на данных MOEX")
    p.add_argument(
        "--preset",
        type=str,
        default="gazp_cagr14_v1",
        help="Готовый пресет. Доступно: gazp_cagr14_v1, gazp_reduced_cost_cagr17_v1",
    )

    p.add_argument("--symbol", type=str, default="GAZP", help="Тикер MOEX, например GAZP, SBER, LKOH")
    p.add_argument("--timeframe", type=str, default="1h", help="1m, 10m, 1h, 1d, 1w, 1M")
    p.add_argument("--since", type=str, default="2025-01-01")
    p.add_argument("--till", type=str, default=None)

    p.add_argument("--initial-cash", type=float, default=100_000.0)
    p.add_argument("--commission", type=float, default=0.0005)
    p.add_argument("--slippage", type=float, default=0.0003)

    p.add_argument("--moex-engine", type=str, default="stock")
    p.add_argument("--moex-market", type=str, default="shares")
    p.add_argument("--moex-board", type=str, default="TQBR")

    p.add_argument("--ema-period", type=int, default=220)
    p.add_argument("--donchian-entry-period", type=int, default=70)
    p.add_argument("--donchian-exit-period", type=int, default=15)
    p.add_argument("--atr-period", type=int, default=14)
    p.add_argument("--atr-stop-mult", type=float, default=2.0)
    p.add_argument("--atr-take-mult", type=float, default=6.0)

    p.add_argument(
        "--require-ema-slope-up",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    p.add_argument("--ema-slope-period", type=int, default=10)
    p.add_argument("--breakout-atr-buffer", type=float, default=0.0)
    p.add_argument("--natr-min", type=float, default=0.0)

    p.add_argument("--risk-per-trade", type=float, default=0.01)
    p.add_argument("--max-capital-pct", type=float, default=1.0)

    p.add_argument("--page-size", type=int, default=500)
    p.add_argument("--max-retries", type=int, default=7)
    p.add_argument("--progress-every-pages", type=int, default=10)
    p.add_argument("--enable-strategy-logs", action="store_true")
    p.add_argument("--log-level", type=str, default="INFO")
    return p


def apply_preset(cfg: BacktestConfig, preset: str | None) -> BacktestConfig:
    if preset is None:
        return cfg

    preset_norm = preset.strip().lower()

    if preset_norm == "gazp_cagr14_v1":
        # Подобранный пресет для GAZP (MOEX, 1h, since=2025-01-01):
        # CAGR ~14.9%, total return ~18.2%, maxDD ~6.3% (окно 2025-01-01..2026-03-18).
        cfg.symbol = "GAZP"
        cfg.timeframe = "1h"
        cfg.since = "2025-01-01"
        cfg.till = None
        cfg.moex_engine = "stock"
        cfg.moex_market = "shares"
        cfg.moex_board = "TQBR"

        cfg.ema_period = 220
        cfg.donchian_entry_period = 70
        cfg.donchian_exit_period = 15
        cfg.atr_period = 14

        cfg.atr_stop_mult = 2.0
        cfg.atr_take_mult = 6.0
        cfg.require_ema_slope_up = False
        cfg.ema_slope_period = 10
        cfg.breakout_atr_buffer = 0.0
        cfg.natr_min = 0.0

        cfg.risk_per_trade = 0.01
        cfg.max_capital_pct = 1.0

        cfg.commission = 0.0005
        cfg.slippage = 0.0003
        return cfg

    if preset_norm == "gazp_reduced_cost_cagr17_v1":
        # Профиль с пониженными издержками (брокер + исполнение):
        # CAGR ~17.6%, total return ~21.6%, maxDD ~9.0% на том же окне.
        cfg.symbol = "GAZP"
        cfg.timeframe = "1h"
        cfg.since = "2025-01-01"
        cfg.till = None
        cfg.moex_engine = "stock"
        cfg.moex_market = "shares"
        cfg.moex_board = "TQBR"

        cfg.ema_period = 200
        cfg.donchian_entry_period = 70
        cfg.donchian_exit_period = 10
        cfg.atr_period = 14

        cfg.atr_stop_mult = 2.0
        cfg.atr_take_mult = 6.0
        cfg.require_ema_slope_up = False
        cfg.ema_slope_period = 10
        cfg.breakout_atr_buffer = 0.02
        cfg.natr_min = 0.1

        cfg.risk_per_trade = 0.012
        cfg.max_capital_pct = 0.90

        cfg.commission = 0.0002
        cfg.slippage = 0.0001
        return cfg

    raise ValueError(
        "Неизвестный пресет: "
        f"{preset}. Доступно: gazp_cagr14_v1, gazp_reduced_cost_cagr17_v1"
    )


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
        moex_engine=args.moex_engine,
        moex_market=args.moex_market,
        moex_board=args.moex_board,
        ema_period=args.ema_period,
        donchian_entry_period=args.donchian_entry_period,
        donchian_exit_period=args.donchian_exit_period,
        atr_period=args.atr_period,
        atr_stop_mult=args.atr_stop_mult,
        atr_take_mult=args.atr_take_mult,
        require_ema_slope_up=args.require_ema_slope_up,
        ema_slope_period=args.ema_slope_period,
        breakout_atr_buffer=args.breakout_atr_buffer,
        natr_min=args.natr_min,
        risk_per_trade=args.risk_per_trade,
        max_capital_pct=args.max_capital_pct,
        page_size=args.page_size,
        max_retries=args.max_retries,
        progress_every_pages=args.progress_every_pages,
        enable_strategy_logs=args.enable_strategy_logs,
    )

    try:
        cfg = apply_preset(cfg, args.preset)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None

    if cfg.donchian_exit_period >= cfg.donchian_entry_period:
        raise SystemExit(
            "Ошибка параметров: --donchian-exit-period должен быть меньше --donchian-entry-period"
        )
    if cfg.ema_slope_period <= 0:
        raise SystemExit("Ошибка параметров: --ema-slope-period должен быть > 0")
    if cfg.natr_min < 0:
        raise SystemExit("Ошибка параметров: --natr-min не может быть отрицательным")
    if cfg.breakout_atr_buffer < 0:
        raise SystemExit("Ошибка параметров: --breakout-atr-buffer не может быть отрицательным")
    if cfg.max_capital_pct <= 0 or cfg.max_capital_pct > 1:
        raise SystemExit("Ошибка параметров: --max-capital-pct должен быть в диапазоне (0, 1]")
    if cfg.risk_per_trade <= 0 or cfg.risk_per_trade > 1:
        raise SystemExit("Ошибка параметров: --risk-per-trade должен быть в диапазоне (0, 1]")

    try:
        metrics = run_backtest(cfg)
        print_metrics(metrics, cfg)
    except KeyboardInterrupt:
        logging.error("Выполнение остановлено пользователем (KeyboardInterrupt)")
        raise SystemExit(130) from None
    except Exception as exc:
        logging.exception("Ошибка выполнения backtest: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
