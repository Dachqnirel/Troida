import backtrader as bt
import pandas as pd
import ccxt
import time


class MacdFuturesStrategy(bt.Strategy):
    params = (
        ('macd_fast', 12),
        ('macd_slow', 26),
        ('macd_signal', 9),
        ('atr_period', 14),
        ('risk_factor', 1.5),  # Множитель ATR для стопа
        ('leverage', 3),       # Плечо
    )

    def __init__(self):
        # MACD
        self.macd = bt.indicators.MACD(
            self.data,
            period_me1=self.params.macd_fast,
            period_me2=self.params.macd_slow,
            period_signal=self.params.macd_signal
        )
        self.histogram = self.macd.macd - self.macd.signal
        self.crossover = bt.indicators.CrossOver(self.histogram, 0.0)

        # ATR для стоп-лосса
        self.atr = bt.indicators.ATR(self.data, period=self.params.atr_period)

        self.order = None
        self.buy_sl = None
        self.sell_sl = None

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f'{dt.strftime("%Y-%m-%d %H:%M")}, {txt}')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'LONG EXECUTED, Price: {order.executed.price:.2f}')
                # Установка стоп-лосса
                sl_price = order.executed.price - self.params.risk_factor * self.atr[0]
                self.sell(exectype=bt.Order.Stop, price=sl_price, size=order.size)
            elif order.issell():
                self.log(f'SHORT EXECUTED, Price: {order.executed.price:.2f}')
                sl_price = order.executed.price + self.params.risk_factor * self.atr[0]
                self.buy(exectype=bt.Order.Stop, price=sl_price, size=abs(order.size))
        self.order = None

    def next(self):
        if self.order:
            return

        # Закрытие текущей позиции при смене сигнала
        if self.position:
            if (self.position.size > 0 and self.crossover < 0) or \
               (self.position.size < 0 and self.crossover > 0):
                self.close()
                return

        # Открытие новых позиций
        if not self.position:
            if self.crossover > 0:  # Сигнал на лонг
                size = (self.broker.get_cash() * self.params.leverage) / self.data.close[0]
                self.buy(size=size)
            elif self.crossover < 0:  # Сигнал на шорт
                size = (self.broker.get_cash() * self.params.leverage) / self.data.close[0]
                self.sell(size=size)


def get_binance_futures_data(symbol='BTC/USDT', timeframe='1h', days=30):
    """Загрузка данных спота (фьючерсы в Backtrader не отличаются по цене)"""
    exchange = ccxt.binance()
    since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('datetime', inplace=True)
    return df


if __name__ == '__main__':
    cerebro = bt.Cerebro()

    # Загрузка данных (используем спотовые, так как цены близки)
    df = get_binance_futures_data('BTC/USDT', '1h', days=60)
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)

    # Настройка "фьючерсного" брокера
    cerebro.broker.setcash(1000.0)
    cerebro.broker.setcommission(commission=0.0004)
    cerebro.addsizer(bt.sizers.PercentSizer, percents=95)

    cerebro.addstrategy(MacdFuturesStrategy, leverage=3)

    print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())
    cerebro.run()
    print('Final Portfolio Value: %.2f' % cerebro.broker.getvalue())

    cerebro.plot(style='line')