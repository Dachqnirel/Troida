#!/usr/bin/env python3

"""
Стратегия для акций: импульсный пробой после сжатия.

Используются индикаторы:
- Bollinger Bands (20, 2.0)
- OBV + SMA(OBV, 20)
- MFI(14)
- Aroon(14)
- Parabolic SAR

Источник данных:
- yfinance (chunk-загрузка исторических OHLCV)

Python: 3.11+
"""

from __future__ import annotations

import argparse
import logging
import math
import time
from collections import deque
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
    since: str | None = "2020-01-01"
    till: str | None = None

    initial_cash: float = 100_000.0
    commission: float = 0.0005
    slippage: float = 0.0003

    risk_per_trade: float = 0.01
    max_capital_pct: float = 0.30

    bb_period: int = 20
    bb_devfactor: float = 2.0
    squeeze_lookback: int = 50
    squeeze_percentile: float = 20.0

    obv_sma_period: int = 20
    mfi_period: int = 14
    aroon_period: int = 14

    mfi_entry_threshold: float = 55.0
    mfi_exit_threshold: float = 45.0
    aroon_up_threshold: float = 70.0
    aroon_down_threshold: float = 30.0

    psar_period: int = 2
    psar_af: float = 0.02
    psar_afmax: float = 0.2

    partial_take_r: float = 2.5
    partial_take_fraction: float = 0.50
    stop_buffer_pct: float = 0.001

    yfinance_chunk_days: int = 365
    max_retries: int = 6
    retry_backoff_sec: float = 2.0
    request_pause_sec: float = 0.25

    enable_strategy_logs: bool = True


class OBVIndicator(bt.Indicator):
    """On-Balance Volume без TA-Lib."""

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


class MFIIndicator(bt.Indicator):
    """Money Flow Index без TA-Lib."""

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


class AroonIndicator(bt.Indicator):
    """Aroon Up/Down без TA-Lib."""

    lines = ("up", "down")
    params = dict(period=14)

    def __init__(self) -> None:
        self.addminperiod(self.p.period)

    def next(self) -> None:
        p = self.p.period

        highs = [float(self.data.high[-i]) for i in range(p)]
        lows = [float(self.data.low[-i]) for i in range(p)]

        bars_since_high = highs.index(max(highs))
        bars_since_low = lows.index(min(lows))

        self.lines.up[0] = ((p - bars_since_high) / p) * 100.0
        self.lines.down[0] = ((p - bars_since_low) / p) * 100.0


class CompressionBreakoutMomentumStrategy(bt.Strategy):
    """Импульсный пробой после сжатия."""

    params = dict(
        bb_period=20,
        bb_devfactor=2.0,
        squeeze_lookback=50,
        squeeze_percentile=20.0,
        obv_sma_period=20,
        mfi_period=14,
        aroon_period=14,
        mfi_entry_threshold=55.0,
        mfi_exit_threshold=45.0,
        aroon_up_threshold=70.0,
        aroon_down_threshold=30.0,
        psar_period=2,
        psar_af=0.02,
        psar_afmax=0.2,
        partial_take_r=2.5,
        partial_take_fraction=0.5,
        stop_buffer_pct=0.001,
        risk_per_trade=0.01,
        max_capital_pct=0.30,
        enable_logs=True,
    )

    def __init__(self) -> None:
        self.bb = bt.ind.BollingerBands(
            self.data.close,
            period=self.p.bb_period,
            devfactor=self.p.bb_devfactor,
        )

        self.obv = OBVIndicator(self.data)
        self.obv_sma = bt.ind.SMA(self.obv, period=self.p.obv_sma_period)

        self.mfi = MFIIndicator(self.data, period=self.p.mfi_period)
        self.aroon = AroonIndicator(self.data, period=self.p.aroon_period)
        self.psar = bt.ind.ParabolicSAR(
            self.data,
            period=self.p.psar_period,
            af=self.p.psar_af,
            afmax=self.p.psar_afmax,
        )

        self.bb_width_window: deque[float] = deque(maxlen=self.p.squeeze_lookback)

        self.entry_order: bt.Order | None = None
        self.exit_order: bt.Order | None = None
        self.stop_order: bt.Order | None = None
        self.partial_tp_order: bt.Order | None = None

        self.pending_entry_stop: float | None = None

        self.entry_price: float | None = None
        self.initial_stop: float | None = None
        self.current_stop: float | None = None
        self.initial_r: float | None = None
        self.partial_target: float | None = None

        self.partial_taken = False
        self.inside_bands_count = 0
        self.last_exit_reason = ""

    def log(self, msg: str) -> None:
        if not self.p.enable_logs:
            return
        dt = self.datas[0].datetime.datetime(0).isoformat()
        logging.info("[%s] %s", dt, msg)

    @staticmethod
    def _is_alive(order: bt.Order | None) -> bool:
        return order is not None and order.alive()

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values:
            return float("nan")
        series = pd.Series(values)
        return float(series.quantile(percentile / 100.0, interpolation="linear"))

    def _bb_width(self) -> float | None:
        mid = float(self.bb.mid[0])
        if mid == 0:
            return None
        top = float(self.bb.top[0])
        bot = float(self.bb.bot[0])
        return (top - bot) / abs(mid)

    def _cancel_order(self, order: bt.Order | None) -> None:
        if self._is_alive(order):
            self.cancel(order)

    def _cancel_protective_orders(self) -> None:
        self._cancel_order(self.stop_order)
        self._cancel_order(self.partial_tp_order)
        self.stop_order = None
        self.partial_tp_order = None

    def _has_pending_entry_or_exit(self) -> bool:
        return self._is_alive(self.entry_order) or self._is_alive(self.exit_order)

    def _entry_signal(self) -> tuple[bool, list[str]]:
        reasons: list[str] = []

        if len(self.bb_width_window) < self.p.squeeze_lookback:
            reasons.append("Недостаточно баров для оценки сжатия")
            return False, reasons

        width_now = self.bb_width_window[-1]
        width_threshold = self._percentile(list(self.bb_width_window), self.p.squeeze_percentile)
        squeeze_ok = width_now <= width_threshold

        close_price = float(self.data.close[0])
        bb_breakout = close_price > float(self.bb.top[0])
        obv_confirm = float(self.obv[0]) > float(self.obv_sma[0])
        mfi_confirm = float(self.mfi[0]) > self.p.mfi_entry_threshold
        aroon_confirm = (
            float(self.aroon.up[0]) > self.p.aroon_up_threshold
            and float(self.aroon.down[0]) < self.p.aroon_down_threshold
        )
        psar_confirm = float(self.psar[0]) < close_price

        checks = [
            (squeeze_ok, f"Сжатие BB: width={width_now:.5f}, p{self.p.squeeze_percentile:.0f}={width_threshold:.5f}"),
            (bb_breakout, f"Пробой BB верхней границы: close={close_price:.2f}, top={float(self.bb.top[0]):.2f}"),
            (obv_confirm, f"OBV подтверждение: obv={float(self.obv[0]):.2f} > obv_sma={float(self.obv_sma[0]):.2f}"),
            (mfi_confirm, f"MFI фильтр: mfi={float(self.mfi[0]):.2f} > {self.p.mfi_entry_threshold:.2f}"),
            (aroon_confirm, f"Aroon фильтр: up={float(self.aroon.up[0]):.2f}, down={float(self.aroon.down[0]):.2f}"),
            (psar_confirm, f"PSAR фильтр: psar={float(self.psar[0]):.2f} < close={close_price:.2f}"),
        ]

        all_ok = True
        for ok, text in checks:
            reasons.append(text)
            if not ok:
                all_ok = False

        return all_ok, reasons

    def _submit_entry(self) -> None:
        close_price = float(self.data.close[0])
        signal_low = float(self.data.low[0])
        psar_value = float(self.psar[0])

        stop_base = min(signal_low, psar_value)
        stop_price = stop_base * (1.0 - self.p.stop_buffer_pct)

        risk_per_share = close_price - stop_price
        if risk_per_share <= 0:
            self.log(
                "ENTRY SKIP: расстояние до стопа <= 0 "
                f"(close={close_price:.2f}, stop={stop_price:.2f})"
            )
            return

        equity = float(self.broker.getvalue())
        cash = float(self.broker.getcash())

        risk_cash = equity * self.p.risk_per_trade
        size_by_risk = risk_cash / risk_per_share
        size_by_capital = (cash * self.p.max_capital_pct) / close_price
        size = math.floor(min(size_by_risk, size_by_capital))

        if size < 1:
            self.log(
                "ENTRY SKIP: рассчитанный размер позиции < 1 "
                f"(size_by_risk={size_by_risk:.4f}, size_by_capital={size_by_capital:.4f})"
            )
            return

        self.pending_entry_stop = stop_price
        self.entry_order = self.buy(size=size)

        self.log(
            "ENTRY ORDER: BUY "
            f"size={size} close_ref={close_price:.2f} stop_ref={stop_price:.2f} "
            f"risk/share={risk_per_share:.4f} risk_cash={risk_cash:.2f}"
        )

    def _submit_manual_exit(self, reason: str) -> None:
        if self._is_alive(self.exit_order):
            return

        self.last_exit_reason = reason
        self._cancel_protective_orders()
        self.exit_order = self.close()
        self.log(f"EXIT ORDER: manual close, reason={reason}")

    def _replace_stop_for_remaining(self, stop_price: float) -> None:
        if self.position.size <= 0:
            return

        stop_price = float(stop_price)
        if stop_price <= 0:
            return

        remaining = float(self.position.size)

        self._cancel_order(self.stop_order)
        self.stop_order = self.sell(
            size=remaining,
            exectype=bt.Order.Stop,
            price=stop_price,
        )
        self.current_stop = stop_price

        self.log(f"STOP UPDATE: size={remaining:.4f}, stop={stop_price:.2f}")

    def _manage_open_position(self) -> None:
        close_price = float(self.data.close[0])

        inside_band = float(self.bb.bot[0]) <= close_price <= float(self.bb.top[0])
        if inside_band:
            self.inside_bands_count += 1
        else:
            self.inside_bands_count = 0

        exit_reasons: list[str] = []

        if float(self.psar[0]) > close_price:
            exit_reasons.append("PSAR выше цены")

        if float(self.mfi[0]) < self.p.mfi_exit_threshold:
            exit_reasons.append(f"MFI < {self.p.mfi_exit_threshold:.2f}")

        if self.inside_bands_count >= 2:
            exit_reasons.append("Цена 2 бара подряд внутри Bollinger Bands")

        if exit_reasons:
            self._submit_manual_exit("; ".join(exit_reasons))
            return

        if self.partial_taken and self.initial_stop is not None:
            psar_trailing = float(self.psar[0])
            desired_stop = max(self.initial_stop, psar_trailing)

            if self.current_stop is None:
                self._replace_stop_for_remaining(desired_stop)
                return

            if desired_stop > self.current_stop and desired_stop < close_price:
                self._replace_stop_for_remaining(desired_stop)

    def _reset_trade_state(self) -> None:
        self.entry_order = None
        self.exit_order = None
        self.stop_order = None
        self.partial_tp_order = None
        self.pending_entry_stop = None

        self.entry_price = None
        self.initial_stop = None
        self.current_stop = None
        self.initial_r = None
        self.partial_target = None

        self.partial_taken = False
        self.inside_bands_count = 0
        self.last_exit_reason = ""

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

            if order is self.entry_order:
                self.entry_order = None
                self.entry_price = float(order.executed.price)

                if self.pending_entry_stop is None:
                    fallback_stop = min(float(self.data.low[0]), float(self.psar[0]))
                    self.pending_entry_stop = fallback_stop * (1.0 - self.p.stop_buffer_pct)

                self.initial_stop = float(self.pending_entry_stop)
                if self.initial_stop >= self.entry_price:
                    self.initial_stop = self.entry_price * (1.0 - 0.005)

                self.initial_r = self.entry_price - self.initial_stop
                if self.initial_r <= 0:
                    self.log("ENTRY ERROR: initial R <= 0, принудительный выход")
                    self._submit_manual_exit("Некорректный R после входа")
                    return

                self.partial_target = self.entry_price + self.p.partial_take_r * self.initial_r
                self.partial_taken = False
                self.inside_bands_count = 0

                full_size = abs(float(order.executed.size))
                self.stop_order = self.sell(
                    size=full_size,
                    exectype=bt.Order.Stop,
                    price=self.initial_stop,
                )
                self.current_stop = self.initial_stop

                partial_size = math.floor(full_size * self.p.partial_take_fraction)
                if partial_size >= full_size:
                    partial_size = max(int(full_size) - 1, 0)

                if partial_size > 0:
                    self.partial_tp_order = self.sell(
                        size=partial_size,
                        exectype=bt.Order.Limit,
                        price=self.partial_target,
                    )
                    self.log(
                        "POST ENTRY: stop установлен, partial TP установлен "
                        f"(stop={self.initial_stop:.2f}, target={self.partial_target:.2f}, partial_size={partial_size})"
                    )
                else:
                    self.partial_tp_order = None
                    self.log(
                        "POST ENTRY: stop установлен, partial TP пропущен (слишком маленький размер позиции) "
                        f"(stop={self.initial_stop:.2f})"
                    )

            elif order is self.partial_tp_order:
                self.partial_tp_order = None
                self.partial_taken = True

                self.log(
                    f"PARTIAL TP: зафиксирована часть позиции по цели {self.partial_target:.2f}"
                )

                if self.position.size > 0 and self.initial_stop is not None:
                    new_stop = max(self.initial_stop, float(self.psar[0]))
                    if new_stop >= float(self.data.close[0]):
                        new_stop = self.initial_stop
                    self._replace_stop_for_remaining(new_stop)

            elif order is self.stop_order:
                self.stop_order = None
                self._cancel_order(self.partial_tp_order)
                self.partial_tp_order = None
                reason = "TRAILING STOP (PSAR)" if self.partial_taken else "INITIAL STOP"
                self.log(f"EXIT: {reason}")
                self._reset_trade_state()

            elif order is self.exit_order:
                self.exit_order = None
                self.log(f"EXIT: manual close completed, reason={self.last_exit_reason}")
                self._reset_trade_state()

        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.log(f"ORDER {order.ref} {order.getstatusname()}")

            if order is self.entry_order:
                self.entry_order = None
                self.pending_entry_stop = None
            elif order is self.stop_order:
                self.stop_order = None
            elif order is self.partial_tp_order:
                self.partial_tp_order = None
            elif order is self.exit_order:
                self.exit_order = None

    def notify_trade(self, trade: bt.Trade) -> None:
        if trade.isclosed:
            self.log(
                f"TRADE CLOSED: gross={trade.pnl:.2f}, net={trade.pnlcomm:.2f}, size={trade.size:.4f}"
            )

    def next(self) -> None:
        width = self._bb_width()
        if width is not None:
            self.bb_width_window.append(width)

        if self._has_pending_entry_or_exit():
            return

        if self.position.size > 0:
            self._manage_open_position()
            return

        self.inside_bands_count = 0

        if self.stop_order is not None or self.partial_tp_order is not None:
            self._cancel_protective_orders()

        signal, reasons = self._entry_signal()
        if not signal:
            return

        self.log("LONG SIGNAL: " + " | ".join(reasons))
        self._submit_entry()


def parse_dt(value: str | None) -> datetime:
    if value is None:
        return datetime.now(tz=UTC)
    raw = value.strip()
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=UTC)


def timeframe_to_yf_interval(timeframe: str) -> str:
    mapping = {
        "1m": "1m",
        "2m": "2m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "60m": "60m",
        "90m": "90m",
        "1h": "60m",
        "1d": "1d",
        "1wk": "1wk",
        "1mo": "1mo",
    }
    if timeframe not in mapping:
        raise ValueError(
            f"Таймфрейм {timeframe} не поддерживается yfinance. "
            f"Используйте: {', '.join(mapping.keys())}"
        )
    return mapping[timeframe]


def timeframe_to_timedelta(timeframe: str) -> timedelta:
    mapping = {
        "1m": timedelta(minutes=1),
        "2m": timedelta(minutes=2),
        "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15),
        "30m": timedelta(minutes=30),
        "60m": timedelta(minutes=60),
        "90m": timedelta(minutes=90),
        "1h": timedelta(hours=1),
        "1d": timedelta(days=1),
        "1wk": timedelta(days=7),
        "1mo": timedelta(days=31),
    }
    if timeframe not in mapping:
        raise ValueError(f"Нет timedelta mapping для timeframe={timeframe}")
    return mapping[timeframe]


def default_chunk_days(timeframe: str) -> int:
    if timeframe == "1m":
        return 7
    if timeframe in {"2m", "5m", "15m", "30m", "90m"}:
        return 60
    if timeframe in {"60m", "1h"}:
        return 720
    return 3650


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
    chunk_days: int | None,
    max_retries: int,
    retry_backoff_sec: float,
    request_pause_sec: float,
) -> pd.DataFrame:
    yf_interval = timeframe_to_yf_interval(timeframe)

    since_dt = parse_dt(since)
    till_dt = parse_dt(till) if till is not None else datetime.now(tz=UTC)

    if since_dt >= till_dt:
        raise ValueError("since должен быть раньше till")

    actual_chunk_days = chunk_days if chunk_days and chunk_days > 0 else default_chunk_days(timeframe)

    logging.info(
        "Старт загрузки yfinance: symbol=%s interval=%s from=%s till=%s chunk_days=%s",
        symbol,
        yf_interval,
        since_dt.isoformat(),
        till_dt.isoformat(),
        actual_chunk_days,
    )

    chunks: list[pd.DataFrame] = []

    start_dt = since_dt
    page = 0

    while start_dt < till_dt:
        page += 1
        end_dt = min(start_dt + timedelta(days=actual_chunk_days), till_dt)

        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")

        chunk_df: pd.DataFrame | None = None

        for attempt in range(1, max_retries + 1):
            try:
                raw = yf.download(
                    tickers=symbol,
                    start=start_str,
                    end=end_str,
                    interval=yf_interval,
                    auto_adjust=False,
                    progress=False,
                    threads=False,
                )
                chunk_df = normalize_yf_columns(raw)
                break
            except Exception as exc:
                wait_s = min(retry_backoff_sec * (2 ** (attempt - 1)), 30.0)
                logging.warning(
                    "Ошибка загрузки yfinance (%s), page=%s attempt=%s/%s, sleep=%.1fs",
                    exc,
                    page,
                    attempt,
                    max_retries,
                    wait_s,
                )
                time.sleep(wait_s)

        if chunk_df is None:
            raise RuntimeError(f"Не удалось загрузить chunk page={page} после всех попыток")

        if not chunk_df.empty:
            chunks.append(chunk_df)
            logging.info("Загружен chunk page=%s, bars=%s", page, len(chunk_df))
        else:
            logging.info("Пустой chunk page=%s", page)

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
        raise ValueError("После объединения chunks не осталось данных")

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
    strat: CompressionBreakoutMomentumStrategy,
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

    buy_hold_return_pct = (float(df["close"].iloc[-1]) / float(df["close"].iloc[0]) - 1.0) * 100.0
    buy_hold_cagr_pct = ((float(df["close"].iloc[-1]) / float(df["close"].iloc[0])) ** (1.0 / years) - 1.0) * 100.0

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
        "win_rate_pct": win_rate_pct,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "buy_hold_return_pct": buy_hold_return_pct,
        "buy_hold_cagr_pct": buy_hold_cagr_pct,
    }


def print_metrics(metrics: dict[str, Any], cfg: BacktestConfig) -> None:
    print("\n===== РЕЗУЛЬТАТЫ BACKTEST =====")
    print("Стратегия:              Импульсный пробой после сжатия")
    print("Источник данных:        yfinance")
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
    print(f"Expectancy / trade:     {metrics['expectancy']:.2f}")
    print(f"Buy & Hold доходность:  {metrics['buy_hold_return_pct']:.2f}%")
    print(f"Buy & Hold CAGR:        {metrics['buy_hold_cagr_pct']:.2f}%")
    print("================================\n")


def run_backtest(cfg: BacktestConfig) -> dict[str, Any]:
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

    data_feed = bt.feeds.PandasData(dataname=df)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(data_feed)

    cerebro.broker.setcash(cfg.initial_cash)
    cerebro.broker.setcommission(commission=cfg.commission)
    cerebro.broker.set_slippage_perc(perc=cfg.slippage)

    cerebro.addstrategy(
        CompressionBreakoutMomentumStrategy,
        bb_period=cfg.bb_period,
        bb_devfactor=cfg.bb_devfactor,
        squeeze_lookback=cfg.squeeze_lookback,
        squeeze_percentile=cfg.squeeze_percentile,
        obv_sma_period=cfg.obv_sma_period,
        mfi_period=cfg.mfi_period,
        aroon_period=cfg.aroon_period,
        mfi_entry_threshold=cfg.mfi_entry_threshold,
        mfi_exit_threshold=cfg.mfi_exit_threshold,
        aroon_up_threshold=cfg.aroon_up_threshold,
        aroon_down_threshold=cfg.aroon_down_threshold,
        psar_period=cfg.psar_period,
        psar_af=cfg.psar_af,
        psar_afmax=cfg.psar_afmax,
        partial_take_r=cfg.partial_take_r,
        partial_take_fraction=cfg.partial_take_fraction,
        stop_buffer_pct=cfg.stop_buffer_pct,
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
    p = argparse.ArgumentParser(description="Backtest стратегии 'Импульсный пробой после сжатия'")

    p.add_argument("--symbol", type=str, default="AAPL")
    p.add_argument("--timeframe", type=str, default="1d")
    p.add_argument("--since", type=str, default="2020-01-01")
    p.add_argument("--till", type=str, default=None)

    p.add_argument("--initial-cash", type=float, default=100_000.0)
    p.add_argument("--commission", type=float, default=0.0005)
    p.add_argument("--slippage", type=float, default=0.0003)

    p.add_argument("--risk-per-trade", type=float, default=0.01)
    p.add_argument("--max-capital-pct", type=float, default=0.30)

    p.add_argument("--bb-period", type=int, default=20)
    p.add_argument("--bb-devfactor", type=float, default=2.0)
    p.add_argument("--squeeze-lookback", type=int, default=50)
    p.add_argument("--squeeze-percentile", type=float, default=20.0)

    p.add_argument("--obv-sma-period", type=int, default=20)
    p.add_argument("--mfi-period", type=int, default=14)
    p.add_argument("--aroon-period", type=int, default=14)

    p.add_argument("--mfi-entry-threshold", type=float, default=55.0)
    p.add_argument("--mfi-exit-threshold", type=float, default=45.0)
    p.add_argument("--aroon-up-threshold", type=float, default=70.0)
    p.add_argument("--aroon-down-threshold", type=float, default=30.0)

    p.add_argument("--psar-period", type=int, default=2)
    p.add_argument("--psar-af", type=float, default=0.02)
    p.add_argument("--psar-afmax", type=float, default=0.2)

    p.add_argument("--partial-take-r", type=float, default=2.5)
    p.add_argument("--partial-take-fraction", type=float, default=0.5)
    p.add_argument("--stop-buffer-pct", type=float, default=0.001)

    p.add_argument("--yfinance-chunk-days", type=int, default=365)
    p.add_argument("--max-retries", type=int, default=6)
    p.add_argument("--retry-backoff-sec", type=float, default=2.0)
    p.add_argument("--request-pause-sec", type=float, default=0.25)

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
        risk_per_trade=args.risk_per_trade,
        max_capital_pct=args.max_capital_pct,
        bb_period=args.bb_period,
        bb_devfactor=args.bb_devfactor,
        squeeze_lookback=args.squeeze_lookback,
        squeeze_percentile=args.squeeze_percentile,
        obv_sma_period=args.obv_sma_period,
        mfi_period=args.mfi_period,
        aroon_period=args.aroon_period,
        mfi_entry_threshold=args.mfi_entry_threshold,
        mfi_exit_threshold=args.mfi_exit_threshold,
        aroon_up_threshold=args.aroon_up_threshold,
        aroon_down_threshold=args.aroon_down_threshold,
        psar_period=args.psar_period,
        psar_af=args.psar_af,
        psar_afmax=args.psar_afmax,
        partial_take_r=args.partial_take_r,
        partial_take_fraction=args.partial_take_fraction,
        stop_buffer_pct=args.stop_buffer_pct,
        yfinance_chunk_days=args.yfinance_chunk_days,
        max_retries=args.max_retries,
        retry_backoff_sec=args.retry_backoff_sec,
        request_pause_sec=args.request_pause_sec,
        enable_strategy_logs=args.enable_strategy_logs,
    )

    if cfg.risk_per_trade <= 0 or cfg.risk_per_trade > 1:
        raise SystemExit("Ошибка: --risk-per-trade должен быть в диапазоне (0, 1]")
    if cfg.max_capital_pct <= 0 or cfg.max_capital_pct > 1:
        raise SystemExit("Ошибка: --max-capital-pct должен быть в диапазоне (0, 1]")
    if cfg.partial_take_fraction <= 0 or cfg.partial_take_fraction >= 1:
        raise SystemExit("Ошибка: --partial-take-fraction должен быть в диапазоне (0, 1)")
    if cfg.squeeze_lookback < 20:
        raise SystemExit("Ошибка: --squeeze-lookback должен быть >= 20")

    try:
        metrics = run_backtest(cfg)
        print_metrics(metrics, cfg)
    except KeyboardInterrupt:
        logging.error("Выполнение остановлено пользователем")
        raise SystemExit(130) from None
    except Exception as exc:
        logging.exception("Ошибка выполнения backtest: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
