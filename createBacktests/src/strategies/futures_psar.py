import math
from typing import Any

import backtrader as bt


class FuturesParabolicSARStrategy(bt.Strategy):
    params = (
        ("contracts", 1),
        ("allow_short", True),
        ("psar_period", 2),
        ("psar_af", 0.02),
        ("psar_afmax", 0.2),
        ("ema_period", 50),
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

        self.psar = bt.indicators.ParabolicSAR(
            self.data,
            period=self.p.psar_period,
            af=self.p.psar_af,
            afmax=self.p.psar_afmax,
        )
        self.ema = bt.indicators.ExponentialMovingAverage(
            self.data.close,
            period=self.p.ema_period,
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

    def _desired_direction(self) -> int:
        close_price = float(self.data.close[0])
        psar_value = float(self.psar[0])
        ema_value = float(self.ema[0])

        if any(math.isnan(value) for value in (close_price, psar_value, ema_value)):
            return 0

        if close_price > psar_value and close_price > ema_value:
            return 1

        if self.p.allow_short and close_price < psar_value and close_price < ema_value:
            return -1

        return 0

    def next(self) -> None:
        if self.order:
            return

        desired_direction = self._desired_direction()
        current_size = int(self.position.size)
        current_direction = 1 if current_size > 0 else -1 if current_size < 0 else 0

        if desired_direction == 0:
            if current_direction != 0:
                self.log("Сигнал стал нейтральным, закрываем позицию")
                self.order = self.order_target_size(target=0)
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
            f"Перестраиваем позицию в {next_side}, "
            f"target_size={target_size}, current_size={current_size}"
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
