import backtrader as bt
import pandas as pd
from pathlib import Path
from backtesting.strategy_template import Strategy, simple_run
from datetime import datetime, timedelta

class DividendDataLoader:
    def __init__(self, ticker):
        self.ticker = ticker
        # Тестовые данные для примера
        self.dividends = {
            # 2020
            datetime(2020, 2, 6): 0.77,  # Q1 2020
            datetime(2020, 5, 7): 0.82,  # Q2 2020
            datetime(2020, 8, 6): 0.82,  # Q3 2020
            datetime(2020, 11, 5): 0.82, # Q4 2020
            
            # 2021
            datetime(2021, 2, 4): 0.205, # Q1 2021 (сплит 4:1 в августе 2020)
            datetime(2021, 5, 6): 0.22,  # Q2 2021
            datetime(2021, 8, 5): 0.22,  # Q3 2021
            datetime(2021, 11, 4): 0.22, # Q4 2021
            
            # 2022
            datetime(2022, 2, 3): 0.22,  # Q1 2022
            datetime(2022, 5, 5): 0.23,  # Q2 2022
            datetime(2022, 8, 4): 0.23,  # Q3 2022
            datetime(2022, 11, 3): 0.23, # Q4 2022
            
            # 2023
            datetime(2023, 2, 9): 0.23,  # Q1 2023
            datetime(2023, 5, 11): 0.24, # Q2 2023
            datetime(2023, 8, 10): 0.24, # Q3 2023
            datetime(2023, 11, 9): 0.24  # Q4 2023
        }

class DividendStrategy(Strategy):
    params = (
        ('lookback_days', 10),
        ('hold_days', 5),
        ('ticker', 'AAPL'),  # Добавляем параметр ticker
    )

    def __init__(self):
        super().__init__()
        self.dividend_loader = DividendDataLoader(self.p.ticker)  # Используем self.p.ticker
        self.active_trade = None

    def next(self):
        super().next()
        current_date = self.datas[0].datetime.datetime(0)

        # Проверка дивидендов
        for ex_date, dividend in self.dividend_loader.dividends.items():
            target_buy_date = ex_date - timedelta(days=self.p.lookback_days)
            
            if current_date.date() == target_buy_date.date() and not self.position:
                self.buy(size=self.calculate_trade_size())
                self.active_trade = {'ex_date': ex_date, 'dividend': dividend}
                break

        if self.active_trade and self.position:
            target_sell_date = self.active_trade['ex_date'] + timedelta(days=self.p.hold_days)
            if current_date >= target_sell_date:
                self.close()
                self.active_trade = None

    def calculate_trade_size(self):
        return int((self.broker.get_cash() * 0.95) / self.data.close[0])

    def notify_trade(self, trade):
        if trade.isclosed and self.active_trade:
            self.broker.add_cash(self.active_trade['dividend'] * trade.size)
            self.log(f'Dividend received: ${self.active_trade["dividend"] * trade.size:.2f}')
            self.active_trade = None

if __name__ == '__main__':
    strategy = simple_run(
        strategy_class=DividendStrategy,
        ticker='AAPL',  # Теперь передаем ticker как параметр
        interval='1d',
        start_date="01.01.20",
        end_date="01.01.23",
        initial_cash=10_000,
        commission=0.001,
        log_orders=True
    )
