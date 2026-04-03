import backtrader as bt
from datetime import datetime
import pandas as pd
import yfinance as yf
import numpy as np


class MultiTickerStrategyOptimized(bt.Strategy):
    params = (
        ('tickers', ['AAPL', 'MSFT', 'GOOGL', 'TLT', 'GS', 'META', 'BRK.A', 'QQQ', 'JPM', 'UNH']),
        ('buy_zones', [0.9, 0.8, 0.7, 0.6, 0.5]),
        ('sell_zone', 0.99),
        ('max_trades', 25),
        ('risk_per_trade', 0.02),  # 🔹 риск 2% на сделку
    )

    def __init__(self):
        self.aths = [0.0] * len(self.datas)
        self.buy_levels = [[0.0] * len(self.p.buy_zones) for _ in range(len(self.datas))]
        self.sell_level = [0.0] * len(self.datas)
        self.scale_counts = [0] * len(self.datas)
        self.total_positions = 0

        # 🔹 индикаторы
        self.ema = [bt.indicators.EMA(d.close, period=200) for d in self.datas]
        self.atr = [bt.indicators.ATR(d, period=14) for d in self.datas]

        self.stop_losses = [None] * len(self.datas)

    def next(self):
        for i, data in enumerate(self.datas):
            if np.isnan(data.close[0]):
                continue

            price = data.close[0]

            # 🔹 обновляем ATH
            if data.high[0] > self.aths[i]:
                self.aths[i] = data.high[0]

            # 🔹 уровни
            for idx, zone in enumerate(self.p.buy_zones):
                self.buy_levels[i][idx] = self.aths[i] * zone

            self.sell_level[i] = self.aths[i] * self.p.sell_zone

            position = self.getposition(data)

            # 🔹 фильтры
            trend_ok = price > self.ema[i][0]
            volatility_ok = self.atr[i][0] > price * 0.005

            # 🔹 выход (sell или stop)
            if position.size > 0:
                if (
                    price > self.sell_level[i] or
                    price < self.stop_losses[i]
                ):
                    self.close(data=data)
                    self.scale_counts[i] = 0
                    self.total_positions -= 1
                continue

            # 🔹 вход
            if self.scale_counts[i] >= len(self.p.buy_zones):
                continue

            if not trend_ok or not volatility_ok:
                continue

            buy_idx = self.scale_counts[i]

            # 🔹 добавил проверку отката (а не просто ниже уровня)
            if price < self.buy_levels[i][buy_idx] and price > self.ema[i][0]:

                if self.total_positions < self.p.max_trades:
                    cash = self.broker.getvalue()
                    risk_amount = cash * self.p.risk_per_trade

                    stop_price = price - self.atr[i][0] * 2

                    risk_per_share = price - stop_price
                    if risk_per_share <= 0:
                        continue

                    size = risk_amount / risk_per_share

                    if size > 0:
                        self.buy(data=data, size=size)

                        self.stop_losses[i] = stop_price
                        self.scale_counts[i] += 1
                        self.total_positions += 1

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                print(f"BUY {order.data._name} @ {order.executed.price:.2f}")
            elif order.issell():
                print(f"SELL {order.data._name} @ {order.executed.price:.2f}")


def load_data(tickers, start, end):
    datafeeds = []
    for ticker in tickers:
        try:
            df = yf.download(ticker, start=start, end=end)

            if df.empty:
                continue

            df.columns = [str(col).lower() for col in df.columns]

            data = bt.feeds.PandasData(dataname=df, name=ticker)
            datafeeds.append(data)

        except:
            continue

    return datafeeds


if __name__ == '__main__':
    cerebro = bt.Cerebro()

    tickers = ['AAPL', 'MSFT', 'GOOGL', 'TLT', 'GS', 'META', 'BRK.A', 'QQQ', 'JPM', 'UNH']
    start_date = datetime(2018, 1, 1)
    end_date = datetime(2025, 1, 1)

    datafeeds = load_data(tickers, start_date, end_date)

    for data in datafeeds:
        cerebro.adddata(data)

    cerebro.addstrategy(MultiTickerStrategyOptimized)

    cerebro.broker.setcash(10000)
    cerebro.broker.setcommission(commission=0.001)

    results = cerebro.run()

    print(f"Final Value: {cerebro.broker.getvalue():.2f}")
