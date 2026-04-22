import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run

class ATRBreakoutOptimized(Strategy):
    """Оптимизированная стратегия пробоя на основе ATR."""

    params = (
        ('atr_period', 20),      # сглаженный период ATR
        ('entry_mult', 1.0),     # множитель ATR для порога входа
        ('atr_stop_mult', 2.0),  # множитель ATR для стоп‑лосса
        ('atr_take_mult', 5.0),  # множитель ATR для тейк‑профита
        ('risk_pct', 0.07),      # 7 % свободного капитала на сделку
    )

    def __init__(self):
        super().__init__()
        self.atr = bt.indicators.ATR(self.datas[0], period=self.p.atr_period)
        self.main_order = None
        self.stop_order = None
        self.take_order = None

    def next(self):
        super().next()
        # пропускаем бар, если есть активный ордер
        if self.main_order is not None:
            return

        # получаем текущую и предыдущую цены закрытия
        close_price = self.data.close[0]
        prev_close = self.data.close[-1]
        atr_val = self.atr[0]
        if atr_val is None or atr_val <= 0:
            return

        long_threshold = prev_close + atr_val * self.p.entry_mult
        short_threshold = prev_close - atr_val * self.p.entry_mult

        in_position = self.position.size != 0
        # если позиции нет, проверяем сигнал на вход
        if not in_position:
            # сигнал на покупку
            if close_price > long_threshold:
                size = self._calc_size(close_price)
                stop = close_price - atr_val * self.p.atr_stop_mult
                take = close_price + atr_val * self.p.atr_take_mult
                self.log('LONG ENTRY SIGNAL')
                self.main_order, self.stop_order, self.take_order = self.buy_bracket(
                    price=close_price,
                    size=size,
                    stopprice=stop,
                    limitprice=take,
                    exectype=bt.Order.Market
                )
            # сигнал на продажу
            elif close_price < short_threshold:
                size = self._calc_size(close_price)
                stop = close_price + atr_val * self.p.atr_stop_mult
                take = close_price - atr_val * self.p.atr_take_mult
                self.log('SHORT ENTRY SIGNAL')
                self.main_order, self.stop_order, self.take_order = self.sell_bracket(
                    price=close_price,
                    size=size,
                    stopprice=stop,
                    limitprice=take,
                    exectype=bt.Order.Market
                )

    def notify_order(self, order):
        super().notify_order(order)
        # очищаем ссылки на стоп и тейк после исполнения
        if order.status == order.Completed:
            if order.exectype in (bt.Order.Stop, bt.Order.Limit):
                self.main_order = None
                self.stop_order = None
                self.take_order = None

    def _calc_size(self, price: float) -> float:
        """Рассчитывает размер позиции исходя из risk_pct."""
        cash = self.broker.get_cash()
        size = (cash * self.p.risk_pct) / price if price > 0 else 0
        return size

    def stop(self):
        super().stop()

# пример запуска:
if __name__ == '__main__':
    strategy, results = simple_run(
        strategy_class=ATRBreakoutOptimized,
        ticker='AAPL',
        interval='1d',
        start_date='01.01.21',
        end_date='28.03.25',
        initial_cash=10_000,
        commission=0.0005,
        log_orders=False,
        plot=True
    )
