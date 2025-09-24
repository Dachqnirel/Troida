import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run, run_on_multiple_tickers
from backtesting.optimization import simple_optimization


class SimpleSMA(Strategy):
    params = (('fast_sma_period', 7), ('slow_sma_period', 30),)

    def __init__(self):
        super().__init__()
        self.sma1 = bt.indicators.SMA(self.datas[0], period=self.params.fast_sma_period)
        self.sma2 = bt.indicators.SMA(self.datas[0], period=self.params.slow_sma_period)
        self.crossover = bt.indicators.CrossOver(self.sma1, self.sma2)

    def notify_order(self, order):
        super().notify_order(order)

    def next(self):
        super().next()
        if self.crossover > 0:
            self.log('BUY SIGNAL')
            self.buy(size=self.calculate_trade_size())
        elif self.crossover < 0:
            self.log('SELL SIGNAL')
            if self.position.size > 0:
                self.close()

    def calculate_trade_size(self):
        cash = self.broker.get_cash()
        size = (cash * 0.1) / self.data.close[0]
        return size

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
                            fast_sma_period=10, slow_sma_period=30)