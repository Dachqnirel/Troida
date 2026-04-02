import backtrader as bt
from backtesting.strategy_template import Strategy, run_on_multiple_tickers


class SimpleSMA(Strategy):
    params = (
        ('fast_sma_period', 7),
        ('slow_sma_period', 30),
        ('trend_sma_period', 100),
        ('atr_period', 14),
        ('risk_per_trade', 0.01),
        ('max_position_fraction', 0.15),
        ('atr_stop_multiplier', 2.0),
        ('atr_take_profit_multiplier', 3.5),
    )

    def __init__(self):
        super().__init__()
        self.sma1 = bt.indicators.SMA(self.datas[0], period=self.params.fast_sma_period)
        self.sma2 = bt.indicators.SMA(self.datas[0], period=self.params.slow_sma_period)
        self.trend_sma = bt.indicators.SMA(
            self.datas[0],
            period=self.params.trend_sma_period
        )
        self.atr = bt.indicators.ATR(self.datas[0], period=self.params.atr_period)
        self.crossover = bt.indicators.CrossOver(self.sma1, self.sma2)
        self.order = None
        self.stop_price = None
        self.take_profit_price = None

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
            atr = float(self.atr[0])
            self.stop_price = (
                trade.price
                - atr * self.params.atr_stop_multiplier
            )
            self.take_profit_price = (
                trade.price
                + atr * self.params.atr_take_profit_multiplier
            )
        elif trade.isclosed:
            self.stop_price = None
            self.take_profit_price = None

    def next(self):
        super().next()
        if self.order:
            return

        price = float(self.data.close[0])
        atr = float(self.atr[0])
        trend_ok = (
            price > self.trend_sma[0]
            and self.sma2[0] > self.trend_sma[0]
        )

        if not self.position and self.crossover > 0 and trend_ok:
            size = self.calculate_trade_size(price, atr)
            if size > 0:
                self.log('BUY SIGNAL')
                self.order = self.buy(size=size)
        elif self.position.size > 0:
            exit_by_cross = self.crossover < 0
            exit_by_stop = price <= self.stop_price
            exit_by_target = price >= self.take_profit_price

            if exit_by_cross or exit_by_stop or exit_by_target:
                self.log('SELL SIGNAL')
                self.order = self.close()

    def calculate_trade_size(self, price, atr):
        stop_distance = atr * self.params.atr_stop_multiplier
        if price <= 0 or stop_distance <= 0:
            return 0.0

        cash = self.broker.get_cash()
        size_by_risk = (cash * self.params.risk_per_trade) / stop_distance
        size_by_cap = (cash * self.params.max_position_fraction) / price
        return max(0.0, min(size_by_risk, size_by_cap))

    def stop(self):
        super().stop()


if __name__ == '__main__':
    tickers = [
    "AAPL"
    ]
    run_on_multiple_tickers(strategy_class=SimpleSMA,
                            tickers=tickers,
                            interval='1d',
                            start_date='01.01.21',
                            end_date='01.03.25',
                            log_orders=True,
                            plot=False,
                            copy_to_clipboard=True,
                            fast_sma_period=10,
                            slow_sma_period=30,
                            trend_sma_period=100,
                            atr_period=14)
