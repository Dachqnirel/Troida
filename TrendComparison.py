import backtrader as bt
import pandas as pd
import ccxt
import time
import os

# ========================
# СТРАТЕГИИ
# ========================

class EmaCross(bt.Strategy):
    params = (('fast_ema_period', 5), ('slow_ema_period', 20),)

    def __init__(self):
        self.ema_fast = bt.indicators.EMA(self.data.close, period=self.params.fast_ema_period)
        self.ema_slow = bt.indicators.EMA(self.data.close, period=self.params.slow_ema_period)
        self.crossover = bt.indicators.CrossOver(self.ema_fast, self.ema_slow)
        self.buy_price = None

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.datetime(0)
        dt_str = dt.strftime('%d.%m.%y %H:%M:%S')
        print(f'{dt_str} {txt}')

    def next(self):
        if self.crossover > 0 and not self.position:
            self.log('BUY SIGNAL')
            self.buy(size=self.calculate_trade_size())
        elif self.crossover < 0 and self.position:
            self.log('SELL SIGNAL')
            self.close()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_price = order.executed.price
                value = order.executed.size * order.executed.price
                self.log(f'BUY EXECUTED, Price: {self.buy_price:.4f}, Position Value: {value:.2f} USD')
            elif order.issell():
                price = order.executed.price
                value = order.executed.size * price
                self.log(f'SELL EXECUTED, Price: {price:.4f}, Position Value: {value:.2f} USD')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'ORDER {order.Status[order.status]}')

    def calculate_trade_size(self):
        cash = self.broker.get_cash() * 0.95
        price = self.data.close[0]
        return cash / price if price > 0 else 0


class SarCross(bt.Strategy):
    params = (('sar_af', 0.02), ('sar_max_af', 0.2),)

    def __init__(self):
        self.sar = bt.indicators.ParabolicSAR(
            self.data,
            af=self.params.sar_af,
            afmax=self.params.sar_max_af
        )
        self.crossover = bt.indicators.CrossOver(self.data.close, self.sar)
        self.buy_price = None

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.datetime(0)
        dt_str = dt.strftime('%d.%m.%y %H:%M:%S')
        print(f'{dt_str} {txt}')

    def next(self):
        if self.crossover > 0 and not self.position:
            self.log('BUY SIGNAL')
            self.buy(size=self.calculate_trade_size())
        elif self.crossover < 0 and self.position:
            self.log('SELL SIGNAL')
            self.close()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_price = order.executed.price
                value = order.executed.size * order.executed.price
                self.log(f'BUY EXECUTED, Price: {self.buy_price:.4f}, Position Value: {value:.2f} USD')
            elif order.issell():
                price = order.executed.price
                value = order.executed.size * price
                self.log(f'SELL EXECUTED, Price: {price:.4f}, Position Value: {value:.2f} USD')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'ORDER {order.Status[order.status]}')

    def calculate_trade_size(self):
        cash = self.broker.get_cash() * 0.95
        price = self.data.close[0]
        return cash / price if price > 0 else 0


class MacdCross(bt.Strategy):
    params = (('macd_fast', 12), ('macd_slow', 26), ('macd_signal', 9),)

    def __init__(self):
        self.macd = bt.indicators.MACD(
            self.data,
            period_me1=self.params.macd_fast,
            period_me2=self.params.macd_slow,
            period_signal=self.params.macd_signal
        )
        self.histogram = self.macd.macd - self.macd.signal
        self.crossover = bt.indicators.CrossOver(self.histogram, 0.0)
        self.buy_price = None

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.datetime(0)
        dt_str = dt.strftime('%d.%m.%y %H:%M:%S')
        print(f'{dt_str} {txt}')

    def next(self):
        if self.crossover > 0 and not self.position:
            self.log('BUY SIGNAL')
            self.buy(size=self.calculate_trade_size())
        elif self.crossover < 0 and self.position:
            self.log('SELL SIGNAL')
            self.close()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_price = order.executed.price
                value = order.executed.size * order.executed.price
                self.log(f'BUY EXECUTED, Price: {self.buy_price:.4f}, Position Value: {value:.2f} USD')
            elif order.issell():
                price = order.executed.price
                value = order.executed.size * price
                self.log(f'SELL EXECUTED, Price: {price:.4f}, Position Value: {value:.2f} USD')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'ORDER {order.Status[order.status]}')

    def calculate_trade_size(self):
        cash = self.broker.get_cash() * 0.95
        price = self.data.close[0]
        return cash / price if price > 0 else 0


# ========================
# ФУНКЦИИ
# ========================

def get_kucoin_data(symbol, timeframe, since=None, limit=5000):
    kucoin = ccxt.kucoin()
    all_data = []
    while True:
        try:
            ohlcv = kucoin.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        except Exception as e:
            print(f"Ошибка KuCoin API: {e}")
            time.sleep(5)
            continue
        if not ohlcv:
            break
        data = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        all_data.append(data)
        since = ohlcv[-1][0] + 1
        time.sleep(5)
    if not all_data:
        raise ValueError("Не удалось загрузить данные")
    df = pd.concat(all_data, ignore_index=True)
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('datetime', inplace=True)
    return df


def run_backtest(strategy_class, data_df, strategy_name, plot=False):
    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_class)
    data = bt.feeds.PandasData(dataname=data_df)
    cerebro.adddata(data)
    cerebro.broker.setcash(1000.0)
    cerebro.broker.setcommission(commission=0.001)

    start_value = cerebro.broker.getvalue()
    cerebro.run()
    end_value = cerebro.broker.getvalue()

    bh_return = ((data_df['close'].iloc[-1] - data_df['close'].iloc[0]) / data_df['close'].iloc[0]) * 100
    strategy_return = ((end_value - start_value) / start_value) * 100

    if plot:
        os.makedirs("plots", exist_ok=True)
        figs = cerebro.plot(style='line', volume=False)
        if figs:
            figs[0].savefig(f"plots/{strategy_name.replace(' ', '_')}.png")
            print(f"График сохранён: plots/{strategy_name.replace(' ', '_')}.png")

    return {
        'strategy': strategy_name,
        'final_value': end_value,
        'strategy_return': strategy_return,
        'bh_return': bh_return
    }


# ========================
# ОСНОВНОЙ БЛОК
# ========================

if __name__ == '__main__':
    print("Загрузка данных с KuCoin...")
    df = get_kucoin_data('BTC/USDT', '5m')
    print(f"Загружено свечей: {len(df)}")

    print("\nЗапуск бэктестов...\n")

    results = []
    strategies = [
        (EmaCross, "Double EMA Crossover"),
        (SarCross, "Parabolic SAR"),
        (MacdCross, "MACD Histogram Cross")
    ]

    for strat_class, name in strategies:
        res = run_backtest(strat_class, df, name, plot=False)
        results.append(res)

    # Вывод сводной таблицы
    print("\n" + "="*70)
    print("СВОДНАЯ ТАБЛИЦА РЕЗУЛЬТАТОВ")
    print("="*70)
    print(f"{'Стратегия':<25} | {'Доходность (%)':<15} | {'Buy & Hold (%)':<15} | {'Преимущество'}")
    print("-"*70)
    for r in results:
        advantage = r['strategy_return'] - r['bh_return']
        print(f"{r['strategy']:<25} | {r['strategy_return']:<15.2f} | {r['bh_return']:<15.2f} | {advantage:+.2f} п.п.")

    print("\n✅ Все графики сохранены в папку 'plots/'")