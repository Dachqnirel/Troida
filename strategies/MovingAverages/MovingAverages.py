from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt
import backtrader.indicators as btind
import pandas as pd
import requests
from datetime import datetime
import time

# ============================================================
# 1. ПАРАМЕТРЫ ТОРГОВЛИ
# ============================================================
SYMBOL = "BTCUSDT"           # Торговая пара
TIMEFRAME = "1h"             # Таймфрейм: 1m, 5m, 15m, 1h, 4h, 1d
LIMIT = 1000                 # Количество свечей (макс 1000 за раз)

# Параметры фьючерсов
INITIAL_CASH = 10000.0       # Начальный капитал USDT
FUTURES_MARGIN = 100.0       # Маржа на 1 контракт
FUTURES_MULT = 1.0           # Мультипликатор
LEVERAGE = 10                # Плечо

# ============================================================
# 2. ЗАГРУЗКА ДАННЫХ С BINANCE (БЕЗ API КЛЮЧЕЙ)
# ============================================================
def get_binance_klines(symbol, interval, limit=500):
    """
    Загрузка исторических данных с Binance Futures
    НЕ ТРЕБУЕТ API КЛЮЧЕЙ - публичный эндпоинт
    """
    url = "https://fapi.binance.com/fapi/v1/klines"
    
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    
    print(f"Загрузка {symbol} {interval}...")
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if not data:
            print("Нет данных")
            return None
            
        # Преобразуем в DataFrame
        candles = []
        for kline in data:
            candles.append({
                'date': pd.to_datetime(kline[0], unit='ms'),
                'open': float(kline[1]),
                'high': float(kline[2]),
                'low': float(kline[3]),
                'close': float(kline[4]),
                'volume': float(kline[5]),
            })
        
        df = pd.DataFrame(candles)
        df.set_index('date', inplace=True)
        
        print(f"Загружено {len(df)} свечей")
        return df
        
    except requests.exceptions.RequestException as e:
        print(f"Ошибка загрузки: {e}")
        return None


# ============================================================
# 3. СТРАТЕГИЯ НА ПЕРЕСЕЧЕНИИ СКОЛЬЗЯЩИХ СРЕДНИХ
# ============================================================
class SMACrossoverStrategy(bt.Strategy):
    """
    Стратегия для фьючерсов:
    - Long: быстрая MA пересекает медленную MA снизу вверх
    - Short: быстрая MA пересекает медленную MA сверху вниз
    """
    
    params = (
        ('fast_ma', 10),      # Период быстрой MA
        ('slow_ma', 30),      # Период медленной MA
        ('ma_type', 'SMA'),   # Тип MA: SMA или EMA
    )
    
    def __init__(self):
        # Создаем скользящие средние
        if self.params.ma_type == 'EMA':
            self.fast_ma = btind.EMA(self.data.close, period=self.params.fast_ma)
            self.slow_ma = btind.EMA(self.data.close, period=self.params.slow_ma)
        else:
            self.fast_ma = btind.SMA(self.data.close, period=self.params.fast_ma)
            self.slow_ma = btind.SMA(self.data.close, period=self.params.slow_ma)
        
        # Сигнал пересечения
        self.crossover = btind.CrossOver(self.fast_ma, self.slow_ma)
        
        # Дополнительные индикаторы для фильтрации (опционально)
        self.rsi = btind.RSI(self.data.close, period=14)
        self.volume_sma = btind.SMA(self.data.volume, period=20)
        
        # Счетчики
        self.trade_count = 0
        
    def log(self, txt):
        """Логирование"""
        dt = self.datas[0].datetime.date(0)
        print(f'[{dt}] {txt}')
    
    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY LONG - Цена: {order.executed.price:.2f}, Размер: {order.executed.size:.4f}')
            else:
                self.log(f'SELL SHORT - Цена: {order.executed.price:.2f}, Размер: {abs(order.executed.size):.4f}')
    
    def notify_trade(self, trade):
        if trade.isclosed:
            self.trade_count += 1
            pnl_percent = (trade.pnlcomm / trade.value) * 100 if trade.value != 0 else 0
            self.log(f'СДЕЛКА #{self.trade_count} ЗАКРЫТА | PnL: {trade.pnlcomm:+.2f} USDT ({pnl_percent:+.2f}%)')
    
    def next(self):
        # Ждем формирования индикаторов
        if len(self.data) < max(self.params.fast_ma, self.params.slow_ma):
            return
        
        # Сигнал на покупку (Fast MA > Slow MA)
        if self.crossover > 0:
            if self.position.size < 0:  # Есть короткая позиция
                self.close()  # Закрываем шорт
                self.log(f"Закрыт SHORT, переход в LONG")
            
            if self.position.size == 0:  # Нет позиции
                self.buy()
                self.log(f"СИГНАЛ LONG | Fast MA ({self.fast_ma[0]:.2f}) > Slow MA ({self.slow_ma[0]:.2f})")
        
        # Сигнал на продажу (Fast MA < Slow MA)
        elif self.crossover < 0:
            if self.position.size > 0:  # Есть длинная позиция
                self.close()  # Закрываем лонг
                self.log(f"Закрыт LONG, переход в SHORT")
            
            if self.position.size == 0:  # Нет позиции
                self.sell()
                self.log(f"СИГНАЛ SHORT | Fast MA ({self.fast_ma[0]:.2f}) < Slow MA ({self.slow_ma[0]:.2f})")


# ============================================================
# 4. ЗАПУСК БЭКТЕСТА
# ============================================================
def run_backtest():
    print("\n" + "="*70)
    print(" СТРАТЕГИЯ НА ПЕРЕСЕЧЕНИИ СКОЛЬЗЯЩИХ СРЕДНИХ - BINANCE FUTURES")
    print("="*70)
    
    # Загружаем данные
    df = get_binance_klines(SYMBOL, TIMEFRAME, LIMIT)
    
    if df is None or len(df) < 50:
        print("Недостаточно данных для бэктеста")
        return
    
    # Конвертируем в формат Backtrader
    data = bt.feeds.PandasData(
        dataname=df,
        datetime=None,
        open='open',
        high='high',
        low='low',
        close='close',
        volume='volume',
        openinterest=-1,
    )
    
    # Создаем движок
    cerebro = bt.Cerebro()
    cerebro.addstrategy(SMACrossoverStrategy)
    cerebro.adddata(data)
    
    # Настройка брокера для фьючерсов
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(
        commission=0.0004,          # Комиссия 0.04%
        margin=FUTURES_MARGIN,
        mult=FUTURES_MULT,
        leverage=LEVERAGE,
    )
    
    # Размер позиции - 95% доступного капитала
    cerebro.addsizer(bt.sizers.PercentSizer, percents=95)
    
    # Добавляем анализаторы
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.01)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    
    # Запускаем
    print("\n" + "-"*70)
    print(f"Начальный капитал: ${INITIAL_CASH:,.2f}")
    print(f"Торговая пара: {SYMBOL} | Таймфрейм: {TIMEFRAME}")
    print(f"Плечо: {LEVERAGE}x | Комиссия: 0.04%")
    print("-"*70)
    
    start_time = time.time()
    results = cerebro.run()
    end_time = time.time()
    
    strat = results[0]
    
    # Результаты
    print("\n" + "="*70)
    print(" РЕЗУЛЬТАТЫ БЭКТЕСТА")
    print("="*70)
    
    final_value = cerebro.broker.getvalue()
    total_return = (final_value - INITIAL_CASH) / INITIAL_CASH * 100
    
    print(f"Финальный капитал: ${final_value:,.2f}")
    print(f"Общая доходность: {total_return:+.2f}%")
    print(f"Время выполнения: {end_time - start_time:.2f} сек")
    
    # Анализ сделок
    trade_analysis = strat.analyzers.trades.get_analysis()
    if 'total' in trade_analysis:
        total_trades = trade_analysis['total']['total']
        won = trade_analysis['won']['total']
        lost = trade_analysis['lost']['total']
        
        print(f"\nСТАТИСТИКА СДЕЛОК:")
        print(f"   Всего сделок: {total_trades}")
        if total_trades > 0:
            print(f"   Прибыльных: {won} ({won/total_trades*100:.1f}%)")
            print(f"   Убыточных: {lost} ({lost/total_trades*100:.1f}%)")
            
            # Средняя прибыль/убыток
            if 'pnl' in trade_analysis['won']:
                avg_win = trade_analysis['won']['pnl']['average']
                avg_loss = trade_analysis['lost']['pnl']['average']
                print(f"   Средняя прибыль: ${avg_win:+.2f}")
                print(f"   Средний убыток: ${avg_loss:+.2f}")
                
                if avg_loss != 0:
                    profit_factor = abs(avg_win / avg_loss)
                    print(f"   Profit Factor: {profit_factor:.2f}")
    
    # Sharpe Ratio
    sharpe = strat.analyzers.sharpe.get_analysis()
    if 'sharperatio' in sharpe and sharpe['sharperatio']:
        print(f"\nSharpe Ratio: {sharpe['sharperatio']:.3f}")
    
    # Просадка
    drawdown = strat.analyzers.drawdown.get_analysis()
    if 'max' in drawdown:
        print(f"Макс. просадка: {drawdown['max']['drawdown']:.2f}%")
        print(f"Длительность: {drawdown['max']['len']} баров")
    
    # Годовой доход
    returns = strat.analyzers.returns.get_analysis()
    if 'rnorm100' in returns:
        print(f"Годовая доходность: {returns['rnorm100']:.2f}%")
    
    # Визуализация
    print("\nГенерация графика...")
    cerebro.plot(style='candlestick', volume=False, figsize=(15, 10))
    
    return results


# ============================================================
# 5. ТЕСТИРОВАНИЕ РАЗНЫХ ПАРАМЕТРОВ
# ============================================================
def test_parameters():
    """Тестирование разных параметров стратегии"""
    print("\n" + "="*70)
    print(" ТЕСТИРОВАНИЕ ПАРАМЕТРОВ")
    print("="*70)
    
    # Разные комбинации MA
    params_to_test = [
        (5, 20, "SMA"),    # (fast, slow, type)
        (10, 30, "SMA"),
        (20, 50, "SMA"),
        (5, 20, "EMA"),
        (10, 30, "EMA"),
        (20, 50, "EMA"),
    ]
    
    results_summary = []
    
    for fast, slow, ma_type in params_to_test:
        print(f"\nТестируем: {ma_type}({fast},{slow})")
        
        # Загружаем данные
        df = get_binance_klines(SYMBOL, TIMEFRAME, LIMIT)
        if df is None:
            continue
        
        # Настраиваем стратегию
        class TestStrategy(SMACrossoverStrategy):
            params = (
                ('fast_ma', fast),
                ('slow_ma', slow),
                ('ma_type', ma_type),
            )
        
        # Запускаем
        data = bt.feeds.PandasData(dataname=df)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(TestStrategy)
        cerebro.adddata(data)
        cerebro.broker.setcash(INITIAL_CASH)
        cerebro.broker.setcommission(commission=0.0004, margin=100, mult=1, leverage=10)
        cerebro.addsizer(bt.sizers.PercentSizer, percents=95)
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        
        results = cerebro.run()
        strat = results[0]
        
        trade_analysis = strat.analyzers.trades.get_analysis()
        final_value = cerebro.broker.getvalue()
        total_return = (final_value - INITIAL_CASH) / INITIAL_CASH * 100
        
        total_trades = trade_analysis.get('total', {}).get('total', 0)
        won = trade_analysis.get('won', {}).get('total', 0)
        
        results_summary.append({
            'params': f"{ma_type}({fast},{slow})",
            'return': total_return,
            'trades': total_trades,
            'win_rate': won/total_trades*100 if total_trades > 0 else 0,
            'final_value': final_value
        })
    
    # Выводим сводку
    print("\n" + "="*70)
    print(" СВОДНАЯ ТАБЛИЦА РЕЗУЛЬТАТОВ")
    print("="*70)
    print(f"{'Параметры':<15} {'Доходность':<12} {'Сделки':<8} {'Win Rate':<10} {'Финальный капитал':<15}")
    print("-"*70)
    
    for r in sorted(results_summary, key=lambda x: x['return'], reverse=True):
        print(f"{r['params']:<15} {r['return']:+.2f}%{'':<6} {r['trades']:<8} {r['win_rate']:.1f}%{'':<5} ${r['final_value']:,.2f}")


# ============================================================
# 6. ЗАПУСК
# ============================================================
if __name__ == '__main__':
    print("""
    ╔════════════════════════════════════════════════════════════════════╗
    ║                    ФЬЮЧЕРСНАЯ СТРАТЕГИЯ                             ║
    ║                                                                     ║
    ║              ПЕРЕСЕЧЕНИЕ СКОЛЬЗЯЩИХ СРЕДНИХ                         ║
    ║                                                                     ║
    ║  LONG  → Быстрая MA пересекает медленную MA СНИЗУ ВВЕРХ        ║
    ║  SHORT → Быстрая MA пересекает медленную MA СВЕРХУ ВНИЗ        ║
    ╚════════════════════════════════════════════════════════════════════╝
    """)
    
    # Выбор режима
    print("Выберите режим:")
    print("1 - Обычный бэктест")
    print("2 - Тестирование параметров")
    
    choice = input("\nВаш выбор (1 или 2): ").strip()
    
    if choice == '2':
        test_parameters()
    else:
        run_backtest()