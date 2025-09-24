import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run
from backtesting.optimization import simple_optimization
import datetime


class MonthlyPriceChange(Strategy):
    """
    Каждое первое число каждого месяца происходит проверка: если цена 30 дней назад была больше на 5%, то происходит покупка. Если ниже на 5%, то продажа.
    Покупки могут выставляться постепенно.
    Каждая покупка составляет 5% от капитала.
    """

    def __init__(self):
        super().__init__()

    def notify_order(self, order):
        super().notify_order(order)

    def next(self):
        super().next()

        current_date = self.datas[0].datetime.date(0)
        if current_date.day != 1:
            return

        one_month_ago_date = current_date - datetime.timedelta(days=30)
        past_month_closing_prices = [
            self.datas[0].close[i]
            for i in range(-len(self.datas[0].close), 0)
            if self.datas[0].datetime.date(i) <= one_month_ago_date
        ]

        if not past_month_closing_prices:
            return

        past_month_closing_price = past_month_closing_prices[-1]
        current_closing_price = self.datas[0].close[0]

        if current_closing_price >= (past_month_closing_price * 1.05):
            self.log('BUY SIGNAL')
            self.buy(size=self.calculate_trade_size())
        elif current_closing_price <= (past_month_closing_price * 0.95):
            self.log('SELL SIGNAL')
            self.close()

    def calculate_trade_size(self):
        cash = self.broker.get_cash()
        size = (cash * 0.05) / self.data.close[0]
        return size

    def stop(self):
        super().stop()


if __name__ == '__main__':
    strategy = simple_run(strategy_class=MonthlyPriceChange,
                          ticker='AAPL',
                          interval='1d',
                          start_date="01.01.21",
                          end_date="01.06.24",
                          log_orders=False)