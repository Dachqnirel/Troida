import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run
from backtesting.optimization import simple_optimization


class SimpleRSI(Strategy):
    """
    Стретегия на основе индикатора RSI. Покупка происходит при перепроданности (RSI < 30), а продажа при перекупленности (RSI > 70).
    В 1 момент времени может быть только одна открытая позиция.
    Каждая покупка составляет 5% от капитала.
    """
    params = (
        ('rsi_period', 6),  # Период RSI
        ('rsi_overbought', 70),  # Уровень перекупленности
        ('rsi_oversold', 30),  # Уровень перепроданности (повышен)
    )

    def __init__(self):
        super().__init__()
        self.rsi = bt.indicators.RSI(self.datas[0], period=self.params.rsi_period)

    def notify_order(self, order):
        super().notify_order(order)

    def next(self):
        super().next()

        if not self.position:
            if self.rsi[0] < self.params.rsi_oversold:
                self.log('BUY SIGNAL')
                self.buy(size=self.calculate_trade_size())
        else:
            if self.rsi[0] > self.params.rsi_overbought:
                self.close()

    def calculate_trade_size(self):
        cash = self.broker.get_cash()
        size = (cash * 0.05) / self.data.close[0]
        return size

    def stop(self):
        super().stop()


if __name__ == '__main__':
    from backtesting.strategy_visualization import compare_price_pnl
    strategy = simple_run(strategy_class=SimpleRSI,
                          ticker='TSLA',
                          interval='1d',
                          start_date="01.01.21",
                          end_date="28.03.25",
                          log_orders=False)
    #compare_price_pnl(strategy, window_days=300)