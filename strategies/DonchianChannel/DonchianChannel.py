import backtrader as bt
import pandas as pd
import ccxt
import time
import datetime as dt


# ---------- Индикатор каналов Дончиана ----------

class DonchianChannel(bt.Indicator):
    """
    Каналы Дончиана:
        upper  – максимум High за period баров
        lower  – минимум Low за period баров
        middle – середина между upper и lower
    """
    lines = ('upper', 'lower', 'middle')
    params = (('period', 20),)

    def __init__(self):
        self.lines.upper = bt.ind.Highest(self.data.high, period=self.p.period)
        self.lines.lower = bt.ind.Lowest(self.data.low, period=self.p.period)
        self.lines.middle = (self.lines.upper + self.lines.lower) / 2.0


# ---------- Стратегия по каналам Дончиана ----------

class DonchianBreakout(bt.Strategy):
    """
    Простая трендовая стратегия:
        - Только лонг.
        - Вход: пробой верхней границы канала (Close > upper[-1]).
        - Выход: пробой вниз нижней границы канала (Close < lower[-1]).
        - Размер позиции: на весь доступный кэш.
    """

    params = (
        ('donchian_period', 20),
    )

    def __init__(self):
        # Индикатор каналов
        self.dc = DonchianChannel(self.data, period=self.p.donchian_period)
        self.buy_price = None
        self.order = None

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.datetime(0)
        dt_str = dt.strftime('%d.%m.%y %H:%M:%S')
        print(f'{dt_str} {txt}')

    def next(self):
        # Если уже есть активный ордер, ничего не делаем
        if self.order:
            return

        close = self.data.close[0]

        # Используем значения канала на предыдущем баре, чтобы избежать "подглядывания"
        upper_prev = self.dc.upper[-1]
        lower_prev = self.dc.lower[-1]

        # ---- Нет позиции: ищем вход ----
        if not self.position:
            if close > upper_prev:
                self.log(f'BUY SIGNAL: Close {close:.4f} > UpperPrev {upper_prev:.4f}')
                self.order = self.buy(size=self.calculate_trade_size())

        # ---- Есть лонг: ищем выход ----
        else:
            if close < lower_prev:
                self.log(f'SELL SIGNAL: Close {close:.4f} < LowerPrev {lower_prev:.4f}')
                self.order = self.close()

    # Обработчик статусов ордеров (покупок и продаж)
    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            self.log(f'ORDER {order.Status[order.status]}')
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_price = order.executed.price
                position_value_usd = order.executed.size * order.executed.price
                self.log(
                    f'BUY EXECUTED, Price: {self.buy_price:.4f}, '
                    f'Position Value: {position_value_usd:.2f} USDT'
                )
            elif order.issell():
                sell_price = order.executed.price
                position_value_usd = abs(order.executed.size) * sell_price
                self.log(
                    f'SELL EXECUTED, Price: {sell_price:.4f}, '
                    f'Position Value: {position_value_usd:.2f} USDT'
                )
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'ORDER {order.Status[order.status]}')

        # Сбрасываем ссылку на текущий ордер
        self.order = None

    # Функция расчета размера позиции для торговли
    def calculate_trade_size(self):
        cash = self.broker.get_cash()
        # Используем весь доступный капитал
        size = cash / self.data.close[0]
        return size

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(
            f'TRADE CLOSED: GROSS PnL {trade.pnl:.2f}, NET PnL {trade.pnlcomm:.2f}'
        )


# ---------- Функция получения исторических данных с KuCoin ----------

def get_kucoin_data(symbol, timeframe, since=None, limit=5000):
    kucoin = ccxt.kucoin()
    all_data = []

    while True:
        ohlcv = kucoin.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        if not ohlcv:
            break

        data = pd.DataFrame(
            ohlcv,
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
        )
        all_data.append(data)

        # временная метка следующей свечи
        since = ohlcv[-1][0] + 1

        # задержка для избежания превышения лимитов API
        time.sleep(1.5)

        # можно сделать ограничение по количеству запросов / дате, если нужно

    all_data = pd.concat(all_data)
    all_data['datetime'] = pd.to_datetime(all_data['timestamp'], unit='ms')
    all_data.set_index('datetime', inplace=True)
    return all_data


# ---------- Основной блок программы ----------

if __name__ == '__main__':
    cerebro = bt.Cerebro()

    # Добавляем стратегию
    cerebro.addstrategy(DonchianBreakout, donchian_period=20)

    # Загружаем данные с KuCoin (пример: ETH/USDT, 5-минутки)
    df = get_kucoin_data('ETH/USDT', '5m')
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)

    # Настройки брокера
    cerebro.broker.setcash(1000.0)           # начальный капитал
    cerebro.broker.setcommission(commission=0.0)  # без комиссии для простоты

    starting_value = cerebro.broker.getvalue()
    print('Starting Portfolio Value: %.2f' % starting_value)

    # Запуск бэктеста
    cerebro.run()

    final_value = cerebro.broker.getvalue()
    print('Final Portfolio Value: %.2f' % final_value)

    # Доходность стратегии
    profit_percent = (final_value - starting_value) / starting_value * 100.0
    print('Percent of Profit (Strategy): %.2f%%' % profit_percent)

    # Доходность "Купи и держи"
    initial_price = df['close'].iloc[0]
    final_price = df['close'].iloc[-1]
    buy_and_hold_profit_percent = (final_price - initial_price) / initial_price * 100.0
    print('Percent of Profit for Buy & Hold: %.2f%%' % buy_and_hold_profit_percent)

    # График
    cerebro.plot(volume=False)