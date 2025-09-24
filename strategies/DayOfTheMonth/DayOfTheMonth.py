import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run
from backtesting.optimization import simple_optimization
import datetime
import pandas as pd
import matplotlib.pyplot as plt


class DayOfTheMonth(Strategy):
    def __init__(self):
        super().__init__()
        self.last_action_day = None
        self.daily_prices = {}  # Словарь для хранения цен по дням
        self.current_month = None
        self.monthly_data = []  # Собранные данные по месяцам

    def next(self):
        current_date = self.data.datetime.date(0)
        day = current_date.day
        price = self.data.close[0]
        
        # Инициализация нового месяца
        if current_date.month != getattr(self, 'current_month', None):
            if hasattr(self, 'current_month'):
                self.save_month_data()
            self.current_month = current_date.month
            self.daily_prices = {d: None for d in range(1, 32)}  # 1-31 дни
            
        # Записываем цену за текущий день
        self.daily_prices[day] = price
        
        # Логика стратегии
        if current_date == self.last_action_day:
            return

        if not self.position and day in [25]:
            self.buy(size=None)
            self.last_action_day = current_date
        elif self.position and day in [16]:
            self.sell(size=self.position.size)
            self.last_action_day = current_date

    def save_month_data(self):
        """Сохраняет данные за месяц перед переходом к новому"""
        if hasattr(self, 'daily_prices') and self.daily_prices:
            self.monthly_data.append(self.daily_prices.copy())

    def normalize_data(self, df):
        """Нормализует цены относительно первого дня каждого месяца"""
        normalized = df.copy()
        for idx, row in df.iterrows():
            base_price = row.loc[row.first_valid_index()]  # Первая доступная цена в месяце
            if pd.notna(base_price):
                normalized.loc[idx] = (row / base_price - 1) * 100  # В процентах
        return normalized

    def create_full_dataframe(self):
        # Сохраняем последний месяц перед созданием DataFrame
        self.save_month_data()
        
        # Создаем DataFrame с днями 1-31
        self.price_df = pd.DataFrame(self.monthly_data)
        self.price_df.columns = [f'Day_{d}' for d in range(1, 32)]
        
        # Нормализуем данные
        self.normalized_df = self.normalize_data(self.price_df)
        
        # Средние значения
        self.mean_prices = self.price_df.mean().reset_index()
        self.mean_prices.columns = ['Day', 'Average_Price']
        
        self.mean_normalized = self.normalized_df.mean().reset_index()
        self.mean_normalized.columns = ['Day', 'Normalized_Price']

    def plot_full_results(self):
        if not hasattr(self, 'normalized_df'):
            self.create_full_dataframe()

        # Подготовка данных
        days = [d.split('_')[1] for d in self.normalized_df.columns]
        avg_normalized = self.normalized_df.mean().values
        
        # График
        plt.figure(figsize=(15, 6))
        plt.bar(days, avg_normalized, 
                color=['skyblue' if x >=0 else 'salmon' for x in avg_normalized])
        
        plt.axhline(0, color='black', linestyle='--')
        plt.title('Среднее изменение цены по дням месяца (нормализовано)')
        plt.xlabel('День месяца')
        plt.ylabel('Изменение цены (%)')
        plt.grid(axis='y', alpha=0.3)
        
        # Подписи для дней с ордерами
        for day in [25, 16]:
            idx = day - 1
            plt.annotate(f'BUY' if day in [25] else 'SELL',
                        (idx, avg_normalized[idx]),
                        textcoords="offset points",
                        xytext=(0,10), ha='center')
        
        plt.tight_layout()
        plt.show()

    def stop(self):
        super().stop()
        self.create_full_dataframe()
        self.plot_full_results()

if __name__ == '__main__':
    simple_run(
        DayOfTheMonth,
        ticker='SBUX',
        interval='1d',
        start_date='01.01.20',
        end_date='31.12.23',
        initial_cash=10000,
        commission=0.001,
        copy_to_clipboard=False,
        log_orders=False
    )