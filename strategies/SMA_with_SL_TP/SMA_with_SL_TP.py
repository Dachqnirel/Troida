import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run


class SMA_with_SL_TP(Strategy):
    params = (
        ('fast_sma_period', 1),
        ('slow_sma_period', 15),
        ('stop_loss', 0.6),
        ('take_profit', 0.2),
    )

    def __init__(self):
        super().__init__()
        self.sma1 = bt.indicators.SMA(self.datas[0], period=self.params.fast_sma_period)
        self.sma2 = bt.indicators.SMA(self.datas[0], period=self.params.slow_sma_period)
        self.crossover = bt.indicators.CrossOver(self.sma1, self.sma2)

        self.main_order = None
        self.stop_loss_order = None
        self.take_profit_order = None

    def notify_order(self, order):
        super().notify_order(order)


    def next(self):
        super().next()


        if self.crossover > 0:
            self.log('BUY SIGNAL')
            if self.position.size == 0:
                # если есть сигнал и нет открытой позиции, то мы создаем 3 ордера (основной, стоп-лосс и тейк-профит)
                self.main_order, self.stop_loss_order, self.take_profit_order = self.buy_bracket(
                    stopprice=self.data.close[0] * (1 - self.params.stop_loss),
                    limitprice=self.data.close[0] * (1 + self.params.take_profit),
                    size=self.calculate_trade_size(),
                    exectype=bt.Order.Market 
                )

        elif self.crossover < 0:
            self.log('SELL SIGNAL')
            if self.position.size > 0:
                # если есть сигнал на продажу и открытая позиция, то мы закрываем позицию
                # и отменяем стоп-лосс и тейк-профит ордера
                if self.stop_loss_order and self.stop_loss_order.alive():
                    self.cancel(self.stop_loss_order)
                    self.stop_loss_order = None
                if self.take_profit_order and self.take_profit_order.alive():
                    self.cancel(self.take_profit_order)
                    self.take_profit_order = None
                
                self.close()
                self.main_order = None
    
  


    def calculate_trade_size(self):
        cash = self.broker.get_cash()
        size = (cash * 0.1) / self.data.close[0]
        return size

    def stop(self):
        super().stop()


if __name__ == '__main__':
    strategy = simple_run(
        strategy_class=SMA_with_SL_TP,
        ticker='AAPL',
        interval='1d',
        start_date='01.01.21',
        end_date='01.03.25',
        log_orders=True,
        plot=True
    )