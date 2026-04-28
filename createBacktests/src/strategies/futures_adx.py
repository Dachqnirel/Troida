import math
from typing import Any

import backtrader as bt


class FuturesADXStrategy(bt.Strategy):
    params = (
        ("contracts", 1),
        ("allow_short", True),
        ("adx_period", 14),
        ("adx_entry_level", 25.0),
        ("adx_exit_level", 20.0),
        ("ema_period", 50),
        ("atr_period", 14),
        ("atr_stop_multiplier", 2.0),
        ("margin", 15_000.0),
        ("margin_buffer", 1.05),
        ("printlog", True),
    )

    def log(self, text: str) -> None:
        if not self.p.printlog:
            return

        dt = self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()} | {text}")

    def __init__(self) -> None:
        self.order = None
        self.executed_orders: list[dict[str, Any]] = []
        self.closed_trades: list[dict[str, Any]] = []

        self.dmi = bt.indicators.DirectionalMovementIndex(
            self.data,
            period=self.p.adx_period,
        )
        self.ema = bt.indicators.ExponentialMovingAverage(
            self.data.close,
            period=self.p.ema_period,
        )
        self.atr = bt.indicators.AverageTrueRange(
            self.data,
            period=self.p.atr_period,
        )

    def _entry_contracts(self) -> int:
        contracts = max(int(self.p.contracts), 0)
        if contracts == 0:
            return 0

        if self.p.margin <= 0:
            return contracts

        margin_with_buffer = self.p.margin * max(float(self.p.margin_buffer), 1.0)
        available_contracts = int(self.broker.getcash() // margin_with_buffer)
        return max(min(contracts, available_contracts), 0)

    def _indicator_values(self) -> tuple[float, float, float, float, float, float]:
        return (
            float(self.data.close[0]),
            float(self.dmi.adx[0]),
            float(self.dmi.plusDI[0]),
            float(self.dmi.minusDI[0]),
            float(self.ema[0]),
            float(self.atr[0]),
        )

    def _has_valid_values(self, values: tuple[float, ...]) -> bool:
        return not any(math.isnan(value) for value in values)

    def _desired_direction(self) -> int:
        close_price, adx_value, plus_di, minus_di, ema_value, _ = self._indicator_values()
        if not self._has_valid_values((close_price, adx_value, plus_di, minus_di, ema_value)):
            return 0

        if adx_value < float(self.p.adx_entry_level):
            return 0

        if plus_di > minus_di and close_price > ema_value:
            return 1

        if self.p.allow_short and minus_di > plus_di and close_price < ema_value:
            return -1

        return 0

    def _stop_triggered(self) -> bool:
        current_size = int(self.position.size)
        if current_size == 0:
            return False

        close_price, _, _, _, _, atr_value = self._indicator_values()
        if not self._has_valid_values((close_price, atr_value)):
            return False

        stop_distance = atr_value * max(float(self.p.atr_stop_multiplier), 0.0)
        if stop_distance == 0:
            return False

        entry_price = float(self.position.price)
        if current_size > 0:
            return close_price <= entry_price - stop_distance

        return close_price >= entry_price + stop_distance

    def next(self) -> None:
        if self.order:
            return

        current_size = int(self.position.size)
        current_direction = 1 if current_size > 0 else -1 if current_size < 0 else 0
        close_price, adx_value, plus_di, minus_di, _, _ = self._indicator_values()

        if current_direction != 0 and self._stop_triggered():
            self.log("Сработал ATR-стоп, закрываем позицию")
            self.order = self.order_target_size(target=0)
            return

        if current_direction != 0 and adx_value < float(self.p.adx_exit_level):
            self.log("ADX опустился ниже уровня выхода, закрываем позицию")
            self.order = self.order_target_size(target=0)
            return

        desired_direction = self._desired_direction()
        if current_direction != 0 and desired_direction == -current_direction:
            side = "SHORT" if desired_direction < 0 else "LONG"
            self.log(
                "DI сменили направление тренда, "
                f"разворачиваемся в {side}: ADX={adx_value:.2f}, "
                f"+DI={plus_di:.2f}, -DI={minus_di:.2f}, close={close_price:.2f}"
            )
        elif desired_direction == 0:
            return

        entry_contracts = self._entry_contracts()
        if entry_contracts == 0:
            if current_direction != 0:
                self.log("Недостаточно средств под гарантийное обеспечение, закрываем позицию")
                self.order = self.order_target_size(target=0)
            return

        target_size = desired_direction * entry_contracts
        if current_size == target_size:
            return

        next_side = "LONG" if target_size > 0 else "SHORT"
        self.log(
            f"Перестраиваем фьючерсную позицию в {next_side}, "
            f"target_size={target_size}, current_size={current_size}, "
            f"ADX={adx_value:.2f}, +DI={plus_di:.2f}, -DI={minus_di:.2f}"
        )
        self.order = self.order_target_size(target=target_size)

    def notify_order(self, order: bt.Order) -> None:
        if order.status in (order.Submitted, order.Accepted):
            return

        if order.status == order.Completed:
            side = "BUY" if order.isbuy() else "SELL"
            executed_at = bt.num2date(order.executed.dt).isoformat()
            order_info = {
                "datetime": executed_at,
                "side": side,
                "size": int(order.executed.size),
                "price": round(float(order.executed.price), 6),
                "value": round(float(order.executed.value), 2),
                "commission": round(float(order.executed.comm), 2),
            }
            self.executed_orders.append(order_info)
            self.log(
                f"Ордер исполнен: {side}, size={order_info['size']}, "
                f"price={order_info['price']}, commission={order_info['commission']}"
            )
        elif order.status in (order.Canceled, order.Margin, order.Rejected):
            self.log(f"Ордер не исполнен: статус={order.getstatusname()}")

        self.order = None

    def notify_trade(self, trade: bt.Trade) -> None:
        if not trade.isclosed:
            return

        trade_info = {
            "open_datetime": bt.num2date(trade.dtopen).isoformat() if trade.dtopen else None,
            "close_datetime": bt.num2date(trade.dtclose).isoformat() if trade.dtclose else None,
            "pnl": round(float(trade.pnl), 2),
            "pnl_after_commission": round(float(trade.pnlcomm), 2),
        }
        self.closed_trades.append(trade_info)
        self.log(
            f"Сделка закрыта: pnl={trade_info['pnl']}, "
            f"pnl_after_commission={trade_info['pnl_after_commission']}"
        )
