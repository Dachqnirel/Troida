import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run
from backtesting.optimization import simple_optimization


class TrailingStopWithSMA(Strategy):
    params = (
        ('fast_sma', 12),
        ('slow_sma', 48),
        ('trend_filter', 150),  # Фильтр тренда
        ('atr_period', 14),  # Для расчета волатильности
        ('risk_per_trade', 0.05),  # 5% риска на сделку
        ('trail_percent', 0.03)  # 3% трейлинг-стоп
    )

    def __init__(self):
        super().__init__()
        self.fast = bt.indicators.SMA(period=self.p.fast_sma)
        self.slow = bt.indicators.SMA(period=self.p.slow_sma)
        self.trend = bt.indicators.SMA(period=self.p.trend_filter)
        self.atr = bt.indicators.ATR(period=self.p.atr_period)
        self.crossover = bt.indicators.CrossOver(self.fast, self.slow)
        self.order = None
        self.entry_price = None

    def notify_order(self, order):
        super().notify_order(order)
        if order.status in [order.Completed]:
            if order.isbuy():
                self.entry_price = order.executed.price
            self.order = None

    def next(self):
        super().next()
        if self.order:
            return

        trend_ok = self.data.close[0] > self.trend[0]
        volatility_ok = self.atr[0] > (self.data.close[0] * 0.01)

        if self.position:
            if (self.position.size > 0 > self.crossover) or (self.position.size < 0 < self.crossover):
                self.close()
            return

        if self.crossover > 0 and trend_ok and volatility_ok:
            size = self.calculate_size()
            self.order = self.buy(size=size)
            self.sell(exectype=bt.Order.StopTrail, trailpercent=self.p.trail_percent)

        elif self.crossover < 0 and not trend_ok and volatility_ok:
            size = self.calculate_size()
            self.order = self.sell(size=size)
            self.buy(exectype=bt.Order.StopTrail, trailpercent=self.p.trail_percent)

    def calculate_size(self):
        risk_cash = self.broker.getcash() * self.p.risk_per_trade
        risk_unit = 2 * self.atr[0]  # Стоп-лосс = 2 ATR
        return int(risk_cash / risk_unit)

    def stop(self):
        super().stop()


if __name__ == '__main__':
    strategy = simple_run(strategy_class=TrailingStopWithSMA,
                          ticker='AMD',
                          interval='1d',
                          start_date="01.01.21",
                          end_date="28.03.25",
                          log_orders=True)
