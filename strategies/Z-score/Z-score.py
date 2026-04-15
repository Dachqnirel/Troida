import backtrader as bt
import requests
import pandas as pd
from datetime import datetime
from collections import deque

class ZScoreFuturesStrategy(bt.Strategy):
    params = (
        ('window', 20),
        ('entry_threshold', 2.0),
        ('exit_threshold', 0.5),
        ('hedge_ratio', 1.0),
    )
    
    def __init__(self):
        self.prices1 = deque(maxlen=self.params.window)
        self.prices2 = deque(maxlen=self.params.window)
        self.spreads = deque(maxlen=self.params.window)
        self.position_type = None
        
    def spread(self, p1, p2):
        return p1 - self.params.hedge_ratio * p2
    
    def zscore(self, spreads):
        if len(spreads) < 2:
            return 0.0
        
        arr = list(spreads)
        current = arr[-1]
        mean = sum(arr) / len(arr)
        var = sum((x - mean) ** 2 for x in arr) / len(arr)
        std = var ** 0.5
        
        return 0.0 if std == 0 else (current - mean) / std
    
    def next(self):
        p1 = self.datas[0].close[0]
        p2 = self.datas[1].close[0]
        
        self.prices1.append(p1)
        self.prices2.append(p2)
        
        if len(self.prices1) < self.params.window:
            return
        
        current_spread = self.spread(p1, p2)
        self.spreads.append(current_spread)
        z = self.zscore(self.spreads)
        
        if self.position_type == 'long' and abs(z) < self.params.exit_threshold:
            self.close(data=self.datas[0])
            self.close(data=self.datas[1])
            self.position_type = None
            
        elif self.position_type == 'short' and abs(z) < self.params.exit_threshold:
            self.close(data=self.datas[0])
            self.close(data=self.datas[1])
            self.position_type = None
        
        elif not self.position_type:
            if z < -self.params.entry_threshold:
                self.buy(data=self.datas[0])
                self.sell(data=self.datas[1])
                self.position_type = 'long'
            elif z > self.params.entry_threshold:
                self.sell(data=self.datas[0])
                self.buy(data=self.datas[1])
                self.position_type = 'short'


def fetch_candles(symbol, interval, category, start_date=None, end_date=None, limit=200):
    """Получение свечей через API парсера Bybit"""
    url = "http://127.0.0.1:8000/candles"
    
    params = {
        "symbol": symbol,
        "interval": interval,
        "category": category,
    }
    
    if start_date and end_date:
        params["start"] = start_date
        params["end"] = end_date
    else:
        params["limit"] = limit
    
    response = requests.get(url, params=params)
    
    if response.status_code != 200:
        print(f"Ошибка загрузки {symbol}: {response.status_code}")
        print(response.text)
        return None
    
    data = response.json()
    return data["candles"]


def candles_to_datafeed(candles):
    """Конвертация свечей в формат Backtrader"""
    if not candles:
        return None
    
    df = pd.DataFrame(candles)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)
    
    return bt.feeds.PandasData(dataname=df)


def safe_number(value, default=0.0):
    """Безопасное преобразование в число"""
    if value is None or value == float('inf') or value == float('-inf'):
        return default
    return float(value)


if __name__ == "__main__":
    SYMBOL1 = "BTCUSDT"
    SYMBOL2 = "ETHUSDT"
    CATEGORY = "linear"
    INTERVAL = "60"
    
    START_DATE = "2024-01-01"
    END_DATE = "2024-12-01"
    
    WINDOW = 20
    ENTRY_THRESHOLD = 2.0
    EXIT_THRESHOLD = 0.5
    HEDGE_RATIO = 1.0
    
    print(f"Загрузка {SYMBOL1}...")
    candles1 = fetch_candles(SYMBOL1, INTERVAL, CATEGORY, START_DATE, END_DATE)
    
    print(f"Загрузка {SYMBOL2}...")
    candles2 = fetch_candles(SYMBOL2, INTERVAL, CATEGORY, START_DATE, END_DATE)
    
    if not candles1 or not candles2:
        print("Ошибка загрузки данных")
        exit(1)
    
    print(f"Загружено: {SYMBOL1} - {len(candles1)} свечей, {SYMBOL2} - {len(candles2)} свечей")
    
    data1 = candles_to_datafeed(candles1)
    data2 = candles_to_datafeed(candles2)
    
    cerebro = bt.Cerebro()
    
    cerebro.adddata(data1)
    cerebro.adddata(data2)
    
    cerebro.addstrategy(
        ZScoreFuturesStrategy,
        window=WINDOW,
        entry_threshold=ENTRY_THRESHOLD,
        exit_threshold=EXIT_THRESHOLD,
        hedge_ratio=HEDGE_RATIO
    )
    
    cerebro.broker.setcash(10000.0)
    cerebro.broker.setcommission(commission=0.0006, margin=100.0, mult=1.0)
    
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    
    print(f"\nНачальный капитал: {cerebro.broker.getvalue():.2f} USDT")
    
    results = cerebro.run()
    strat = results[0]
    
    final_value = cerebro.broker.getvalue()
    print(f"\n=== РЕЗУЛЬТАТЫ ===")
    print(f"Конечный капитал: {final_value:.2f} USDT")
    print(f"Доходность: {(final_value - 10000) / 10000 * 100:.2f}%")
    
    # Безопасное получение коэффициента Шарпа
    sharpe_analysis = strat.analyzers.sharpe.get_analysis()
    sharpe_value = sharpe_analysis.get('sharperatio', None)
    if sharpe_value is None or sharpe_value == float('inf') or sharpe_value == float('-inf'):
        print("Коэффициент Шарпа: Н/Д (недостаточно данных)")
    else:
        print(f"Коэффициент Шарпа: {sharpe_value:.2f}")
    
    # Безопасное получение просадки
    dd_analysis = strat.analyzers.drawdown.get_analysis()
    max_dd = dd_analysis.get('max', {})
    dd_value = max_dd.get('drawdown', 0) if max_dd else 0
    print(f"Максимальная просадка: {dd_value:.2f}%")
    
    # Безопасное получение доходности
    ret_analysis = strat.analyzers.returns.get_analysis()
    ret_value = ret_analysis.get('rnorm100', 0)
    if ret_value is None or ret_value == float('inf') or ret_value == float('-inf'):
        print("Годовая доходность: Н/Д")
    else:
        print(f"Годовая доходность: {ret_value:.2f}%")
    
    cerebro.plot(style='candlestick')