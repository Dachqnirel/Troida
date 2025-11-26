import math
import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run


class HullMovingAverage(bt.Indicator):
    """
    Индикатор Hull Moving Average (HMA).
    Формула:
        HMA_N = WMA_{sqrt(N)}( 2 * WMA_{N/2}(P) - WMA_N(P) )
    """
    lines = ('hma',)
    params = (
        ('period', 20),
    )

    def __init__(self):
        n = int(self.p.period)
        half_n = max(int(n / 2), 1)
        sqrt_n = max(int(math.sqrt(n)), 1)

        # Взвешенные скользящие
        wma_half = bt.indicators.WeightedMovingAverage(self.data, period=half_n)
        wma_full = bt.indicators.WeightedMovingAverage(self.data, period=n)

        # Промежуточный ряд
        diff = 2.0 * wma_half - wma_full

        # Финальная HMA
        self.lines.hma = bt.indicators.WeightedMovingAverage(diff, period=sqrt_n)


class HMAStrategy(Strategy):
    """
    Простая трендовая стратегия по Hull Moving Average.

    Логика:
    - Лонг, когда цена пересекает HMA снизу вверх.
    - Шорт, когда цена пересекает HMA сверху вниз.
    - Выход по:
        * обратному пересечению,
        * стоп-лоссу,
        * тейк-профиту.
    """
    params = (
        ('hma_period', 20),     # период HMA
        ('position_size', 0.1), # доля капитала в сделке
        ('stop_loss', 0.02),    # стоп-лосс 2%
        ('take_profit', 0.04),  # тейк-профит 4%
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.data0 = self.datas[0]
        self.hma = HullMovingAverage(self.data0, period=self.params.hma_period)

        self.in_position = False
        self.is_long = None
        self.entry_price = None

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            side = 'BUY' if order.isbuy() else 'SELL'
            self.log(
                f'{side} EXECUTED, Price: {order.executed.price:.2f}, '
                f'Size: {order.executed.size:.4f}'
            )

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'ORDER {order.Status[order.status]}')

    def calculate_trade_size(self, data):
        """Размер позиции как доля от кэша."""
        cash = self.broker.get_cash()
        size = (cash * self.params.position_size) / data.close[0]
        return size

    def next(self):
        super().next()

        price = self.data0.close[0]
        hma_curr = self.hma[0]

        if len(self.data0) < 2:
            return

        price_prev = self.data0.close[-1]
        hma_prev = self.hma[-1]

        # Нет позиции — ищем вход
        if not self.in_position:
            # Лонг: пересечение снизу вверх
            if price > hma_curr and price_prev <= hma_prev:
                size = self.calculate_trade_size(self.data0)
                self.buy(data=self.data0, size=size)
                self.in_position = True
                self.is_long = True
                self.entry_price = price
                self.log(f'ENTER LONG at {price:.2f}')

            # Шорт: пересечение сверху вниз
            elif price < hma_curr and price_prev >= hma_prev:
                size = self.calculate_trade_size(self.data0)
                self.sell(data=self.data0, size=size)
                self.in_position = True
                self.is_long = False
                self.entry_price = price
                self.log(f'ENTER SHORT at {price:.2f}')

        # Уже в позиции — контролируем выход
        else:
            if self.is_long:
                profit_pct = (price - self.entry_price) / self.entry_price
                exit_by_cross = price < hma_curr and price_prev >= hma_prev
            else:
                profit_pct = (self.entry_price - price) / self.entry_price
                exit_by_cross = price > hma_curr and price_prev <= hma_prev

            exit_by_sl = profit_pct <= -self.params.stop_loss
            exit_by_tp = profit_pct >= self.params.take_profit

            if exit_by_sl or exit_by_tp or exit_by_cross:
                self.close(data=self.data0)
                self.log(
                    f'EXIT position at {price:.2f}, '
                    f'PnL: {profit_pct * 100:.2f}%'
                )
                self.in_position = False
                self.is_long = None
                self.entry_price = None


if __name__ == '__main__':
    # Пример самостоятельного прогона стратегии
    strategy = simple_run(
        strategy_class=HMAStrategy,
        ticker='AAPL',
        interval='1d',
        start_date="01.01.2020",
        end_date="01.06.2022",
        log_orders=True,
        hma_period=20,
        position_size=0.1,
        stop_loss=0.02,
        take_profit=0.04,
    )
