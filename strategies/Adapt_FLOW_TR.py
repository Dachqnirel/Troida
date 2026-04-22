
"""
Adaptive Flow Trend стратегия, адаптированная под акции MOEX.

Логика:
- EMA200 как фильтр глобального тренда
- KAMA как адаптивная сигнальная средняя
- MFI(14) как фильтр импульса
- OBV + SMA(OBV,20) как фильтр потока объема
- NATR(14) как фильтр режима волатильности
- ATR(14) для стопа/тейка и размера позиции

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



@dataclass(slots=True)
class BacktestConfig:
    symbol: str = "SBER"
    timeframe: str = "1d"
    since: str | int | None = "2020-01-01"
    till: str | None = None
    initial_cash: float = 100_000.0
    commission: float = 0.0005
    slippage: float = 0.0003
    moex_engine: str = "stock"
    moex_market: str = "shares"
    moex_board: str = "TQBR"
    ema_period: int = 80
    kama_period: int = 12
    mfi_period: int = 10
    obv_sma_period: int = 20
    natr_period: int = 14
    atr_period: int = 14
    natr_min: float = 0.1
    mfi_entry: float = 50.0
    mfi_exit: float = 30.0
    atr_stop_mult: float = 1.0
    atr_take_mult: float = 8.0
    risk_per_trade: float = 0.02
    max_capital_pct: float = 0.70
    page_size: int = 500
    max_retries: int = 7
    progress_every_pages: int = 10
    enable_strategy_logs: bool = False



class KAMA(bt.Indicator):
    """Kaufman Adaptive Moving Average (без TA-Lib)."""

    lines = ("kama",)
    params = dict(period=10, fast=2, slow=30)

    def __init__(self) -> None:
        self.addminperiod(self.p.period + 1)

    def next(self) -> None:
        period = self.p.period
        close = self.data.close

        change = abs(close[0] - close[-period])
        volatility = 0.0
        for i in range(period):
            volatility += abs(close[-i] - close[-i - 1])

        er = (change / volatility) if volatility > 0 else 0.0
        fast_sc = 2.0 / (self.p.fast + 1.0)
        slow_sc = 2.0 / (self.p.slow + 1.0)
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2

        prev = self.lines.kama[-1] if len(self) > period + 1 else close[-1]
        self.lines.kama[0] = prev + sc * (close[0] - prev)


class MFI(bt.Indicator):
    """Money Flow Index (без TA-Lib)."""

    lines = ("mfi",)
    params = dict(period=14)

    def __init__(self) -> None:
        self.addminperiod(self.p.period + 1)

    def next(self) -> None:
        p = self.p.period
        pos_flow = 0.0
        neg_flow = 0.0

        for i in range(p):
            tp_curr = (self.data.high[-i] + self.data.low[-i] + self.data.close[-i]) / 3.0
            tp_prev = (self.data.high[-i - 1] + self.data.low[-i - 1] + self.data.close[-i - 1]) / 3.0
            mf = tp_curr * self.data.volume[-i]

            if tp_curr > tp_prev:
                pos_flow += mf
            elif tp_curr < tp_prev:
                neg_flow += mf

        if neg_flow == 0:
            self.lines.mfi[0] = 100.0
            return

        money_ratio = pos_flow / neg_flow
        self.lines.mfi[0] = 100.0 - (100.0 / (1.0 + money_ratio))


class OBV(bt.Indicator):
    """On-Balance Volume (без TA-Lib)."""

    lines = ("obv",)

    def __init__(self) -> None:
        self.addminperiod(1)

    def next(self) -> None:
        if len(self) == 1:
            self.lines.obv[0] = 0.0
            return

        prev_obv = self.lines.obv[-1]
        if math.isnan(prev_obv):
            prev_obv = 0.0

        if self.data.close[0] > self.data.close[-1]:
            self.lines.obv[0] = prev_obv + self.data.volume[0]
        elif self.data.close[0] < self.data.close[-1]:
            self.lines.obv[0] = prev_obv - self.data.volume[0]
        else:
            self.lines.obv[0] = prev_obv


class NATR(bt.Indicator):
    """Normalized ATR = ATR/Close * 100."""

    lines = ("natr",)
    params = dict(period=14)

    def __init__(self) -> None:
        atr = bt.ind.ATR(self.data, period=self.p.period)
        self.lines.natr = (atr / self.data.close) * 100.0



class AdaptiveFlowTrendStrategy(bt.Strategy):
    params = dict(
        ema_period=200,
        kama_period=10,
        mfi_period=14,
        obv_sma_period=20,
        natr_period=14,
        atr_period=14,
        natr_min=0.25,
        mfi_entry=50,
        mfi_exit=45,
        atr_stop_mult=2.0,
        atr_take_mult=3.0,
        risk_per_trade=0.01,
        max_capital_pct=0.20,
        enable_logs=False,
    )

    def __init__(self) -> None:
        self.ema200 = bt.ind.EMA(self.data.close, period=self.p.ema_period)
        self.kama = KAMA(self.data, period=self.p.kama_period)
        self.mfi = MFI(self.data, period=self.p.mfi_period)
        self.obv = OBV(self.data)
        self.obv_sma = bt.ind.SMA(self.obv, period=self.p.obv_sma_period)
        self.natr = NATR(self.data, period=self.p.natr_period)
        self.atr = bt.ind.ATR(self.data, period=self.p.atr_period)

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
        for o in (self.stop_order, self.take_order):
            if o is not None and o.alive():
                self.cancel(o)
        self.stop_order = None
        self.take_order = None

    def long_entry_signal(self) -> bool:
        return (
            self.data.close[0] > self.ema200[0]
            and self.data.close[0] > self.kama[0]
            and self.mfi[0] > self.p.mfi_entry
            and self.obv[0] > self.obv_sma[0]
            and self.natr[0] > self.p.natr_min
        )

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
                self.log("EXIT: выход по условиям стратегии")
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

        if self.position.size > 0:
            if self.data.close[0] < self.kama[0] or self.mfi[0] < self.p.mfi_exit:
                self.log(
                    f"EXIT SIGNAL: close={self.data.close[0]:.2f}, "
                    f"kama={self.kama[0]:.2f}, mfi={self.mfi[0]:.2f}"
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
                f"LONG SIGNAL: close={close:.2f}, ema200={self.ema200[0]:.2f}, "
                f"kama={self.kama[0]:.2f}, mfi={self.mfi[0]:.2f}, "
                f"obv={self.obv[0]:.2f}, obv_sma={self.obv_sma[0]:.2f}, "
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



def safe_get(dct: dict[str, Any], path: list[str], default: Any = None) -> Any:
    cur: Any = dct
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def collect_metrics(
    strat: AdaptiveFlowTrendStrategy,
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
        AdaptiveFlowTrendStrategy,
        ema_period=cfg.ema_period,
        kama_period=cfg.kama_period,
        mfi_period=cfg.mfi_period,
        obv_sma_period=cfg.obv_sma_period,
        natr_period=cfg.natr_period,
        atr_period=cfg.atr_period,
        natr_min=cfg.natr_min,
        mfi_entry=cfg.mfi_entry,
        mfi_exit=cfg.mfi_exit,
        atr_stop_mult=cfg.atr_stop_mult,
        atr_take_mult=cfg.atr_take_mult,
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


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Adaptive Flow Trend стратегия на данных MOEX")
    p.add_argument(
        "--preset",
        type=str,
        default="sber_cagr12_v1",
        help="Готовый пресет. Доступно: sber_optimized_v1, sber_cagr12_v1",
    )
    p.add_argument("--symbol", type=str, default="SBER", help="Тикер MOEX, например SBER, GAZP, LKOH")
    p.add_argument("--timeframe", type=str, default="1d", help="1m, 10m, 1h, 1d, 1w, 1M")
    p.add_argument("--since", type=str, default="2020-01-01")
    p.add_argument("--till", type=str, default=None)
    p.add_argument("--initial-cash", type=float, default=100_000.0)
    p.add_argument("--commission", type=float, default=0.0005)
    p.add_argument("--slippage", type=float, default=0.0003)

    p.add_argument("--moex-engine", type=str, default="stock")
    p.add_argument("--moex-market", type=str, default="shares")
    p.add_argument("--moex-board", type=str, default="TQBR")

    p.add_argument("--ema-period", type=int, default=80)
    p.add_argument("--kama-period", type=int, default=12)
    p.add_argument("--mfi-period", type=int, default=10)
    p.add_argument("--obv-sma-period", type=int, default=20)
    p.add_argument("--natr-period", type=int, default=14)
    p.add_argument("--atr-period", type=int, default=14)
    p.add_argument("--natr-min", type=float, default=0.1)
    p.add_argument("--mfi-entry", type=float, default=50.0)
    p.add_argument("--mfi-exit", type=float, default=30.0)
    p.add_argument("--atr-stop-mult", type=float, default=1.0)
    p.add_argument("--atr-take-mult", type=float, default=8.0)
    p.add_argument("--risk-per-trade", type=float, default=0.02)
    p.add_argument("--max-capital-pct", type=float, default=0.70)

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
    if preset_norm == "sber_optimized_v1":
        cfg.symbol = "SBER"
        cfg.timeframe = "1d"
        cfg.since = "2020-01-01"
        cfg.till = None
        cfg.moex_engine = "stock"
        cfg.moex_market = "shares"
        cfg.moex_board = "TQBR"

        cfg.ema_period = 150
        cfg.kama_period = 8
        cfg.mfi_period = 14
        cfg.obv_sma_period = 14
        cfg.natr_period = 14
        cfg.atr_period = 14

        cfg.natr_min = 0.2
        cfg.mfi_entry = 52.0
        cfg.mfi_exit = 43.0
        cfg.atr_stop_mult = 1.6
        cfg.atr_take_mult = 3.6
        cfg.risk_per_trade = 0.012
        cfg.max_capital_pct = 0.30
        return cfg

    if preset_norm == "sber_cagr12_v1":
        cfg.symbol = "SBER"
        cfg.timeframe = "1d"
        cfg.since = "2020-01-01"
        cfg.till = None
        cfg.moex_engine = "stock"
        cfg.moex_market = "shares"
        cfg.moex_board = "TQBR"

        cfg.ema_period = 80
        cfg.kama_period = 12
        cfg.mfi_period = 10
        cfg.obv_sma_period = 20
        cfg.natr_period = 14
        cfg.atr_period = 14

        cfg.natr_min = 0.1
        cfg.mfi_entry = 50.0
        cfg.mfi_exit = 30.0
        cfg.atr_stop_mult = 1.0
        cfg.atr_take_mult = 8.0
        cfg.risk_per_trade = 0.03
        cfg.max_capital_pct = 0.70
        return cfg

    raise ValueError(
        f"Неизвестный пресет: {preset}. Доступно: sber_optimized_v1, sber_cagr12_v1"
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
        kama_period=args.kama_period,
        mfi_period=args.mfi_period,
        obv_sma_period=args.obv_sma_period,
        natr_period=args.natr_period,
        atr_period=args.atr_period,
        natr_min=args.natr_min,
        mfi_entry=args.mfi_entry,
        mfi_exit=args.mfi_exit,
        atr_stop_mult=args.atr_stop_mult,
        atr_take_mult=args.atr_take_mult,
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
