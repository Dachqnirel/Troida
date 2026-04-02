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
    Улучшенная трендовая стратегия по Hull Moving Average.

    Логика:
    - Вход по пересечению цены и HMA только в сторону старшего тренда.
    - Размер позиции ограничен риском на сделку и максимальной загрузкой капитала.
    - Выход по обратному пересечению, ATR-стопу, трейлинг-стопу и тейк-профиту.
    """
    params = (
        ('hma_period', 20),
        ('trend_ema_period', 55),
        ('atr_period', 14),
        ('risk_per_trade', 0.02),
        ('max_position_size', 0.2),
        ('atr_stop_multiplier', 2.3),
        ('atr_trail_multiplier', 1.4),
        ('atr_take_profit_multiplier', 4.0),
    )

    def __init__(self):
        super().__init__()

        self.data0 = self.datas[0]
        self.hma = HullMovingAverage(self.data0, period=self.params.hma_period)
        self.trend_ema = bt.indicators.EMA(self.data0, period=self.params.trend_ema_period)
        self.atr = bt.indicators.ATR(self.data0, period=self.params.atr_period)
        self.price_cross = bt.indicators.CrossOver(self.data0.close, self.hma)

        self.order = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.highest_price = None
        self.lowest_price = None

    def notify_order(self, order):
        super().notify_order(order)

        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            self.order = None

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.order = None

    def notify_trade(self, trade):
        if trade.justopened:
            self._set_entry_state(trade.price)
        elif trade.isclosed:
            self.log(
                f'TRADE CLOSED, Gross PnL: {trade.pnl:.2f}, '
                f'Net PnL: {trade.pnlcomm:.2f}'
            )
            self._reset_position_state()

    def _set_entry_state(self, price):
        atr = max(float(self.atr[0]), 1e-8)

        self.entry_price = price
        self.highest_price = price
        self.lowest_price = price

        if self.position.size > 0:
            self.stop_price = price - atr * self.params.atr_stop_multiplier
            self.take_profit_price = (
                price + atr * self.params.atr_take_profit_multiplier
            )
        else:
            self.stop_price = price + atr * self.params.atr_stop_multiplier
            self.take_profit_price = (
                price - atr * self.params.atr_take_profit_multiplier
            )

    def _reset_position_state(self):
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.highest_price = None
        self.lowest_price = None

    def calculate_trade_size(self, price, atr):
        stop_distance = atr * self.params.atr_stop_multiplier
        if price <= 0 or stop_distance <= 0:
            return 0.0

        cash = self.broker.get_cash()
        risk_size = (cash * self.params.risk_per_trade) / stop_distance
        capped_size = (cash * self.params.max_position_size) / price
        return max(0.0, min(risk_size, capped_size))

    def next(self):
        super().next()

        if self.order:
            return

        price = float(self.data0.close[0])
        atr = float(self.atr[0])
        hma_rising = self.hma[0] > self.hma[-1]
        hma_falling = self.hma[0] < self.hma[-1]
        trend_long = price > self.trend_ema[0]
        trend_short = price < self.trend_ema[0]

        if not self.position:
            if self.price_cross > 0 and trend_long and hma_rising:
                size = self.calculate_trade_size(price, atr)
                if size > 0:
                    self.log(f'ENTER LONG at {price:.2f}, size={size:.4f}')
                    self.order = self.buy(data=self.data0, size=size)
            elif self.price_cross < 0 and trend_short and hma_falling:
                size = self.calculate_trade_size(price, atr)
                if size > 0:
                    self.log(f'ENTER SHORT at {price:.2f}, size={size:.4f}')
                    self.order = self.sell(data=self.data0, size=size)
            return

        if self.position.size > 0:
            self.highest_price = max(self.highest_price, price)
            trailing_stop = self.highest_price - (
                atr * self.params.atr_trail_multiplier
            )
            self.stop_price = max(self.stop_price, trailing_stop)

            exit_by_cross = self.price_cross < 0 and hma_falling
            exit_by_stop = price <= self.stop_price
            exit_by_target = price >= self.take_profit_price

            if exit_by_cross or exit_by_stop or exit_by_target:
                reason = 'cross' if exit_by_cross else 'stop' if exit_by_stop else 'target'
                self.log(f'EXIT LONG by {reason} at {price:.2f}')
                self.order = self.close(data=self.data0)
        else:
            self.lowest_price = min(self.lowest_price, price)
            trailing_stop = self.lowest_price + (
                atr * self.params.atr_trail_multiplier
            )
            self.stop_price = min(self.stop_price, trailing_stop)

            exit_by_cross = self.price_cross > 0 and hma_rising
            exit_by_stop = price >= self.stop_price
            exit_by_target = price <= self.take_profit_price

            if exit_by_cross or exit_by_stop or exit_by_target:
                reason = 'cross' if exit_by_cross else 'stop' if exit_by_stop else 'target'
                self.log(f'EXIT SHORT by {reason} at {price:.2f}')
                self.order = self.close(data=self.data0)


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
        trend_ema_period=55,
        atr_period=14,
        risk_per_trade=0.02,
        max_position_size=0.2,
        atr_stop_multiplier=2.3,
        atr_trail_multiplier=1.4,
        atr_take_profit_multiplier=4.0,
    )
