import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run
import numpy as np


class PairTradingStrategyOptimized(Strategy):
    params = (
        ('lookback_period', 30),
        ('entry_threshold', 1.2),
        ('exit_threshold', 0.4),
        ('stop_threshold', 2.5),  # 🔹 стоп по z-score
        ('min_correlation', 0.5),  # 🔹 фильтр корреляции
        ('risk_per_trade', 0.02),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.data0 = self.datas[0]
        self.data1 = self.datas[1]

        self.price_history0 = []
        self.price_history1 = []

        self.spread = []
        self.in_position = False

        # 🔹 индикаторы
        self.atr0 = bt.indicators.ATR(self.data0, period=14)
        self.atr1 = bt.indicators.ATR(self.data1, period=14)

    def next(self):
        super().next()

        self.price_history0.append(self.data0.close[0])
        self.price_history1.append(self.data1.close[0])

        if len(self.price_history0) < self.params.lookback_period:
            return

        p0 = np.array(self.price_history0[-self.params.lookback_period:])
        p1 = np.array(self.price_history1[-self.params.lookback_period:])

        # 🔹 корреляция
        corr = np.corrcoef(p0, p1)[0, 1]
        if corr < self.params.min_correlation:
            return

        # 🔹 нормализация
        norm0 = p0 / np.mean(p0)
        norm1 = p1 / np.mean(p1)

        spread = norm0 - norm1
        mean = np.mean(spread)
        std = np.std(spread)

        if std == 0:
            return

        z = (spread[-1] - mean) / std

        self.log(f'z-score: {z:.2f} | corr: {corr:.2f}')

        # 🔹 фильтр волатильности
        if self.atr0[0] == 0 or self.atr1[0] == 0:
            return

        if not self.in_position:

            if z > self.params.entry_threshold:
                self.open_pair(short0=True)

            elif z < -self.params.entry_threshold:
                self.open_pair(short0=False)

        else:
            # 🔹 выход
            if abs(z) < self.params.exit_threshold or abs(z) > self.params.stop_threshold:
                self.close(self.data0)
                self.close(self.data1)
                self.in_position = False

    def open_pair(self, short0):
        cash = self.broker.getvalue()
        risk = cash * self.params.risk_per_trade

        price0 = self.data0.close[0]
        price1 = self.data1.close[0]

        # 🔹 балансируем позиции
        size0 = risk / self.atr0[0]
        size1 = risk / self.atr1[0]

        if short0:
            self.sell(data=self.data0, size=size0)
            self.buy(data=self.data1, size=size1)
            self.log(f'SHORT {self.data0._name} / LONG {self.data1._name}')
        else:
            self.buy(data=self.data0, size=size0)
            self.sell(data=self.data1, size=size1)
            self.log(f'LONG {self.data0._name} / SHORT {self.data1._name}')

        self.in_position = True

    def stop(self):
        super().stop()
        if self.in_position:
            self.close(self.data0)
            self.close(self.data1)


if __name__ == '__main__':
    simple_run(
        strategy_class=PairTradingStrategyOptimized,
        ticker=['PEP', 'AAPL'],
        interval='1d',
        start_date="01.01.20",
        end_date="01.06.22",
        log_orders=True
    )
