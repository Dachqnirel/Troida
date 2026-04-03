import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run
import pandas as pd
import matplotlib.pyplot as plt


class DayOfTheMonthOptimized(Strategy):
    def __init__(self):
        super().__init__()

        self.last_action_day = None
        self.daily_prices = {}
        self.current_month = None
        self.monthly_data = []

        # 🔹 Новое
        self.ema = bt.indicators.EMA(self.data.close, period=200)
        self.atr = bt.indicators.ATR(self.data, period=14)

        self.best_buy_day = 25
        self.best_sell_day = 16

        self.entry_price = None
        self.stop_loss = None
        self.take_profit = None

    def next(self):
        current_date = self.data.datetime.date(0)
        day = current_date.day
        price = self.data.close[0]

        # Новый месяц
        if current_date.month != getattr(self, 'current_month', None):
            if hasattr(self, 'current_month'):
                self.save_month_data()
            self.current_month = current_date.month
            self.daily_prices = {d: None for d in range(1, 32)}

        self.daily_prices[day] = price

        if current_date == self.last_action_day:
            return

        # 🔹 Фильтры
        trend_ok = price > self.ema[0]
        volatility_ok = self.atr[0] > self.data.close[0] * 0.005

        # 🔹 Вход
        if not self.position and day == self.best_buy_day and trend_ok and volatility_ok:
            self.buy()
            self.entry_price = price
            self.stop_loss = price - self.atr[0] * 2
            self.take_profit = price + self.atr[0] * 3
            self.last_action_day = current_date

        # 🔹 Выход
        elif self.position:
            if (
                day == self.best_sell_day or
                price <= self.stop_loss or
                price >= self.take_profit
            ):
                self.sell(size=self.position.size)
                self.last_action_day = current_date

    def save_month_data(self):
        if self.daily_prices:
            self.monthly_data.append(self.daily_prices.copy())

    def find_best_days(self):
        df = pd.DataFrame(self.monthly_data)

        returns = df.pct_change(axis=1)

        mean_returns = returns.mean()

        self.best_buy_day = mean_returns.idxmax() + 1
        self.best_sell_day = mean_returns.idxmin() + 1

        print(f'Best BUY day: {self.best_buy_day}')
        print(f'Best SELL day: {self.best_sell_day}')

    def stop(self):
        super().stop()

        self.save_month_data()
        self.find_best_days()


if __name__ == '__main__':
    simple_run(
        DayOfTheMonthOptimized,
        ticker='SBUX',
        interval='1d',
        start_date='01.01.20',
        end_date='31.12.23',
        initial_cash=10000,
        commission=0.001,
        log_orders=False
    )
