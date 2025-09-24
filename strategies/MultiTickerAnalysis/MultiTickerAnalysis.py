import backtrader as bt
from datetime import datetime
import pandas as pd
import yfinance as yf
import numpy as np

class MultiTickerStrategy(bt.Strategy):
    params = (
        ('tickers', ['AAPL', 'MSFT', 'GOOGL', 'TLT', 'GS', 'META', 'BRK.A', 'QQQ', 'JPM', 'UNH']),
        ('buy_zones', [0.9, 0.8, 0.7, 0.6, 0.5]),
        ('sell_zone', 0.99),
        ('max_trades', 25),
        ('starting_value', 10000),
        ('leverage', 2),
    )

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print(f"{dt.isoformat()} | {txt}")

    def __init__(self):
        # Инициализация переменных для хранения ATH и уровней входа/выхода
        self.aths = [0.0] * len(self.datas)
        self.buy_levels = [[0.0] * len(self.p.buy_zones) for _ in range(len(self.datas))]
        self.sell_level = [0.0] * len(self.datas)
        self.scale_counts = [0] * len(self.datas)  # Счетчик скальпирований по каждому тикеру
        self.total_positions = 0  # Общее количество открытых позиций

    def next(self):
        # Обновление ATH и уровней входа/выхода для каждого тикера
        for i, data in enumerate(self.datas):
            if np.isnan(data.high[0]) or np.isnan(data.close[0]):
                continue
                
            current_high = data.high[0]
            if current_high > self.aths[i]:
                self.aths[i] = current_high
                
            for idx, zone in enumerate(self.p.buy_zones):
                self.buy_levels[i][idx] = self.aths[i] * zone
            self.sell_level[i] = self.aths[i] * self.p.sell_zone

        # Проверка условий выхода из позиций
        for i, data in enumerate(self.datas):
            if np.isnan(data.close[0]):
                continue
                
            position = self.getposition(data)
            if position.size > 0 and data.close[0] > self.sell_level[i]:
                self.close(data=data)
                self.total_positions -= self.scale_counts[i]
                self.scale_counts[i] = 0

        # Проверка условий входа в позиции
        for i, data in enumerate(self.datas):
            if np.isnan(data.close[0]):
                continue
                
            if self.scale_counts[i] >= len(self.p.buy_zones):
                continue  # Пропуск, если уже сделано максимальное количество скальпирований

            current_price = data.close[0]
            buy_idx = self.scale_counts[i]
            
            if current_price < self.buy_levels[i][buy_idx]:
                if self.total_positions < self.p.max_trades:
                    current_value = self.broker.getvalue()
                    cash_per_trade = (self.p.leverage * current_value) / self.p.max_trades
                    
                    if current_price > 0:  # Защита от деления на ноль
                        size = cash_per_trade / current_price
                        if size > 0:  # Защита от отрицательных размеров позиции
                            self.buy(data=data, size=size)
                            self.scale_counts[i] += 1
                            self.total_positions += 1

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f"BUY EXECUTED | Ticker: {order.data._name}, Price: {order.executed.price:.2f}, Size: {order.executed.size:.2f}")
            elif order.issell():
                self.log(f"SELL EXECUTED | Ticker: {order.data._name}, Price: {order.executed.price:.2f}, Size: {order.executed.size:.2f}")
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"ORDER CANCELED/MARGIN/REJECTED | Ticker: {order.data._name}")

def load_data(tickers, start, end):
    datafeeds = []
    for ticker in tickers:
        try:
            df = yf.download(ticker, start=start, end=end)
            if df.empty:
                print(f"⚠️ Нет данных для {ticker}, пропускаем...")
                continue
                
            # Преобразование названий колонок в нижний регистр
            df.columns = [str(col).lower() for col in df.columns]
            
            # Добавление данных в cerebro
            data = bt.feeds.PandasData(dataname=df, name=ticker)
            datafeeds.append(data)
        except Exception as e:
            print(f"❌ Ошибка загрузки {ticker}: {str(e)}")
            continue
            
    return datafeeds

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    # Параметры
    tickers = ['AAPL', 'MSFT', 'GOOGL', 'TLT', 'GS', 'META', 'BRK.A', 'QQQ', 'JPM', 'UNH']
    start_date = datetime(2018, 1, 1)
    end_date = datetime(2025, 1, 1)
    start_value = 10000
    max_trades = 25
    leverage = 2
    
    # Загрузка данных
    datafeeds = load_data(tickers, start_date, end_date)
    for data in datafeeds:
        cerebro.adddata(data)
    
    # Добавление стратегии
    cerebro.addstrategy(MultiTickerStrategy,
                        tickers=tickers,
                        buy_zones=[0.9, 0.8, 0.7, 0.6, 0.5],
                        sell_zone=0.99,
                        max_trades=max_trades,
                        starting_value=start_value,
                        leverage=leverage)
    
    # Настройки брокера
    cerebro.broker.setcash(start_value)
    cerebro.broker.setcommission(commission=0.001)
    
    # Добавление анализаторов
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    
    # Запуск стратегии
    results = cerebro.run()
    strat = results[0]
    
    # Вывод результатов
    final_value = cerebro.broker.getvalue()
    final_value = final_value if not np.isnan(final_value) else start_value
    print(f"\nFinal Portfolio Value: ${final_value:,.2f}")
    
    # Sharpe Ratio
    sharpe_analysis = strat.analyzers.sharpe.get_analysis()
    sharpe_ratio = sharpe_analysis.get('sharperatio', 0.0)
    if not isinstance(sharpe_ratio, (int, float)) or np.isnan(sharpe_ratio):
        sharpe_ratio = 0.0
    print(f"Sharpe Ratio: {sharpe_ratio:.2f}")
    
    # Max Drawdown
    dd_analysis = strat.analyzers.drawdown.get_analysis()
    max_drawdown = dd_analysis.get('max', {}).get('drawdown', 0.0)
    if not isinstance(max_drawdown, (int, float)) or np.isnan(max_drawdown):
        max_drawdown = 0.0
    print(f"Max Drawdown: {max_drawdown:.2f}%")
    
    # Построение графика без отображения объема
    cerebro.plot(iplot=False, volume=False)