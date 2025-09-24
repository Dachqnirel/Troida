import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run
from backtesting.optimization import simple_optimization


class BollingerBreakout(Strategy):
    """
    Стратегия на основе индикатора Bollinger Bands.
    Покупка происходит при пробое верхней границы, а продажа при пробое нижней границы (нижней полосы).
    Может быть несколько открытых позиций.
    Каждая покупка составляет 5% от капитала.
    """
    params = (('bollinger_period', 6), ('devfactor', 2.0),)

    def __init__(self):
        super().__init__()
        self.bb = bt.indicators.BollingerBands(self.datas[0], period=self.params.bollinger_period, devfactor=self.params.devfactor)

    def next(self):
        super().next()
        if self.data.close[0] > self.bb.lines.top[0]:
            self.log(f'BUY SIGNAL at: {self.data.close[0]:.2f}')
            self.buy(size=self.calculate_trade_size())

        elif self.data.close[0] < self.bb.lines.bot[0]:
            self.log(f'SELL SIGNAL at: {self.data.close[0]:.2f}')
            if self.position.size > 0:
                self.close()

    def calculate_trade_size(self):
        cash = self.broker.get_cash()
        size = (cash * 0.05) / self.data.close[0]
        return size

    def stop(self):
        super().stop()


if __name__ == '__main__':
    strategy = simple_run(strategy_class=BollingerBreakout,
                          ticker='AAPL',
                          interval='1d',
                          start_date="01.01.21",
                          end_date="01.06.24",
                          log_orders=False)