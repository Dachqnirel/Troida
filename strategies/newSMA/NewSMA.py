import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run, run_on_multiple_tickers
from backtesting.optimization import simple_optimization
import numpy as np


class EnhancedSMA(Strategy):
    """
    Улучшенная SMA стратегия с дополнительными фильтрами:
    - Использование трех скользящих средних для подтверждения тренда
    - Фильтр RSI для избежания ложных сигналов
    - Фильтр объема для подтверждения пробития
    - Динамический размер позиции на основе волатильности
    - Трейлинг-стоп для защиты прибыли
    - Частичное закрытие позиции
    - Фильтр по ADX для определения силы тренда
    """
    params = (
        # Параметры скользящих средних
        ('fast_sma_period', 10),
        ('middle_sma_period', 30),
        ('slow_sma_period', 50),
        
        # Дополнительные фильтры
        ('use_volume_filter', True),
        ('volume_ma_period', 20),
        ('volume_threshold', 1.2),  # Объем выше среднего в X раз
        
        ('use_rsi_filter', True),
        ('rsi_period', 14),
        ('rsi_oversold', 40),  # Повышенный порог для фильтрации слабых сигналов
        ('rsi_overbought', 60),
        
        ('use_adx_filter', True),
        ('adx_period', 14),
        ('adx_threshold', 25),  # Минимальная сила тренда
        
        # Управление позицией
        ('position_size', 0.1),  # 10% от капитала на сделку
        ('use_dynamic_position', True),  # Динамический размер позиции на основе ATR
        
        ('use_trailing_stop', True),
        ('trailing_stop_percent', 5.0),
        
        ('use_partial_exit', True),
        ('partial_exit_ratio', 0.5),  # Закрывать 50% при первом сигнале
        
        ('take_profit_percent', 15.0),
        ('stop_loss_percent', 5.0),  # Жесткий стоп-лосс
        
        # Фильтр времени удержания
        ('max_holding_bars', 50),  # Максимальное количество баров удержания позиции
    )
    
    def __init__(self):
        super().__init__()
        
        # Три скользящие средние
        self.sma_fast = bt.indicators.SMA(self.datas[0].close, period=self.params.fast_sma_period)
        self.sma_middle = bt.indicators.SMA(self.datas[0].close, period=self.params.middle_sma_period)
        self.sma_slow = bt.indicators.SMA(self.datas[0].close, period=self.params.slow_sma_period)
        
        # Пересечения
        self.crossover_fast_middle = bt.indicators.CrossOver(self.sma_fast, self.sma_middle)
        self.crossover_middle_slow = bt.indicators.CrossOver(self.sma_middle, self.sma_slow)
        
        # RSI для фильтрации
        if self.params.use_rsi_filter:
            self.rsi = bt.indicators.RSI(self.datas[0].close, period=self.params.rsi_period)
        
        # ADX для определения силы тренда
        if self.params.use_adx_filter:
            self.adx = bt.indicators.ADX(self.datas[0], period=self.params.adx_period)
        
        # Индикатор объема
        if self.params.use_volume_filter and hasattr(self.datas[0], 'volume'):
            self.volume_ma = bt.indicators.SMA(self.datas[0].volume, period=self.params.volume_ma_period)
        
        # ATR для динамического позиционирования
        self.atr = bt.indicators.ATR(self.datas[0], period=14)
        
        # Переменные для отслеживания
        self.entry_price = None
        self.entry_bar = None
        self.trailing_stop_price = None
        self.position_size_initial = None
        
    def is_bullish_alignment(self):
        """Проверка правильного расположения скользящих средних (бычий порядок)"""
        return self.sma_fast[0] > self.sma_middle[0] > self.sma_slow[0]
    
    def is_bearish_alignment(self):
        """Проверка правильного расположения скользящих средних (медвежий порядок)"""
        return self.sma_fast[0] < self.sma_middle[0] < self.sma_slow[0]
    
    def is_volume_confirmed(self):
        """Проверка подтверждения объема"""
        if not self.params.use_volume_filter or not hasattr(self.datas[0], 'volume'):
            return True
        if self.volume_ma[0] > 0:
            return self.datas[0].volume[0] > self.volume_ma[0] * self.params.volume_threshold
        return True
    
    def is_rsi_confirmed(self, bullish=True):
        """Проверка RSI для подтверждения сигнала"""
        if not self.params.use_rsi_filter:
            return True
        if bullish:
            # Для бычьего сигнала RSI должен быть выше перепроданности, но не перекуплен
            return self.rsi[0] > self.params.rsi_oversold and self.rsi[0] < 70
        else:
            # Для медвежьего сигнала RSI должен быть ниже перекупленности, но не перепродан
            return self.rsi[0] < self.params.rsi_overbought and self.rsi[0] > 30
    
    def is_trend_strong(self):
        """Проверка силы тренда через ADX"""
        if not self.params.use_adx_filter:
            return True
        return self.adx[0] > self.params.adx_threshold
    
    def calculate_dynamic_position_size(self):
        """Динамический расчет размера позиции на основе ATR"""
        cash = self.broker.get_cash()
        
        if self.params.use_dynamic_position:
            # Используем ATR для определения риска
            risk_per_trade = cash * 0.02  # Риск 2% от капитала на сделку
            atr_value = self.atr[0]
            
            if atr_value > 0:
                # Размер позиции = Риск / (ATR * множитель)
                size = risk_per_trade / (atr_value * 1.5)
                # Ограничиваем максимальный размер позиции
                max_size = (cash * self.params.position_size) / self.data.close[0]
                size = min(size, max_size)
                return size
        
        # Стандартный расчет
        return (cash * self.params.position_size) / self.data.close[0]
    
    def update_trailing_stop(self):
        """Обновление трейлинг-стопа"""
        if self.position and self.params.use_trailing_stop and self.entry_price:
            current_price = self.data.close[0]
            
            if self.position.size > 0:  # Long позиция
                new_stop = current_price * (1 - self.params.trailing_stop_percent / 100)
                if self.trailing_stop_price is None or new_stop > self.trailing_stop_price:
                    self.trailing_stop_price = new_stop
                    self.log(f'Trailing stop updated to {self.trailing_stop_price:.2f}')
                
                if current_price <= self.trailing_stop_price:
                    self.log(f'Trailing stop triggered at {current_price:.2f}')
                    self.close()
                    self.reset_position_tracking()
    
    def reset_position_tracking(self):
        """Сброс отслеживания позиции"""
        self.entry_price = None
        self.entry_bar = None
        self.trailing_stop_price = None
        self.position_size_initial = None
    
    def check_take_profit_stop_loss(self):
        """Проверка тейк-профит и стоп-лосс"""
        if self.position and self.entry_price:
            current_price = self.data.close[0]
            profit_percent = (current_price - self.entry_price) / self.entry_price * 100
            
            # Тейк-профит
            if profit_percent >= self.params.take_profit_percent:
                self.log(f'Take profit triggered: {profit_percent:.2f}%')
                self.close()
                self.reset_position_tracking()
                return True
            
            # Стоп-лосс
            if profit_percent <= -self.params.stop_loss_percent:
                self.log(f'Stop loss triggered: {profit_percent:.2f}%')
                self.close()
                self.reset_position_tracking()
                return True
        
        return False
    
    def check_max_holding_period(self):
        """Проверка максимального времени удержания"""
        if self.position and self.entry_bar is not None:
            bars_held = len(self.data) - self.entry_bar
            if bars_held >= self.params.max_holding_bars:
                self.log(f'Max holding period reached: {bars_held} bars')
                self.close()
                self.reset_position_tracking()
                return True
        return False
    
    def next(self):
        super().next()
        
        # Проверка достаточности данных
        if len(self.datas[0]) < self.params.slow_sma_period:
            return
        
        # Обновление трейлинг-стопа для открытой позиции
        if self.position:
            self.update_trailing_stop()
            if self.check_take_profit_stop_loss():
                return
            if self.check_max_holding_period():
                return
            
            # Частичное закрытие при достижении определенной прибыли
            if (self.params.use_partial_exit and 
                self.position.size == self.position_size_initial and 
                self.entry_price):
                
                current_price = self.data.close[0]
                profit_percent = (current_price - self.entry_price) / self.entry_price * 100
                
                if profit_percent >= self.params.take_profit_percent * 0.6:  # 60% от тейк-профита
                    close_size = int(self.position.size * self.params.partial_exit_ratio)
                    if close_size > 0:
                        self.sell(size=close_size)
                        self.log(f'Partial exit: closed {close_size} units at {profit_percent:.2f}% profit')
                        self.position_size_initial = self.position.size  # Обновляем оставшийся размер
        
        # Поиск сигналов на вход
        if not self.position:
            # Бычий сигнал: fast пересекает middle снизу вверх
            if self.crossover_fast_middle > 0:
                # Дополнительные условия для качественного сигнала
                if (self.is_bullish_alignment() or self.sma_fast[0] > self.sma_slow[0]) and \
                   self.is_volume_confirmed() and \
                   self.is_rsi_confirmed(bullish=True) and \
                   self.is_trend_strong():
                    
                    self.log(f'BUY SIGNAL - Fast SMA({self.params.fast_sma_period}) crossed above '
                            f'Middle SMA({self.params.middle_sma_period})')
                    
                    size = self.calculate_dynamic_position_size()
                    self.buy(size=size)
                    self.entry_price = self.data.close[0]
                    self.entry_bar = len(self.data)
                    self.position_size_initial = size
                    self.trailing_stop_price = None
                    self.log(f'BUY executed: size={size:.4f}, price={self.data.close[0]:.2f}')
            
            # Альтернативный сигнал: все три SMA в бычьем порядке и цена выше fast SMA
            elif self.is_bullish_alignment() and self.data.close[0] > self.sma_fast[0]:
                if self.is_volume_confirmed() and self.is_rsi_confirmed(bullish=True) and self.is_trend_strong():
                    self.log(f'BUY SIGNAL - Bullish alignment with price above fast SMA')
                    
                    size = self.calculate_dynamic_position_size()
                    self.buy(size=size)
                    self.entry_price = self.data.close[0]
                    self.entry_bar = len(self.data)
                    self.position_size_initial = size
                    self.trailing_stop_price = None
                    self.log(f'BUY executed: size={size:.4f}, price={self.data.close[0]:.2f}')
        
        # Сигналы на выход (если не сработали стопы/тейк-профиты)
        elif self.position:
            # Медвежий сигнал: fast пересекает middle сверху вниз
            if self.crossover_fast_middle < 0:
                self.log(f'SELL SIGNAL - Fast SMA({self.params.fast_sma_period}) crossed below '
                        f'Middle SMA({self.params.middle_sma_period})')
                self.close()
                self.reset_position_tracking()
            
            # Выход при медвежьем расположении SMA
            elif self.is_bearish_alignment():
                self.log(f'SELL SIGNAL - Bearish alignment detected')
                self.close()
                self.reset_position_tracking()
            
            # Выход по RSI (перекупленность)
            elif self.params.use_rsi_filter and self.rsi[0] > 75:
                self.log(f'SELL SIGNAL - RSI overbought: {self.rsi[0]:.2f}')
                self.close()
                self.reset_position_tracking()
    
    def notify_order(self, order):
        """Обработка исполнения ордеров"""
        super().notify_order(order)
        
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY EXECUTED, Price: {order.executed.price:.2f}, '
                        f'Cost: {order.executed.value:.2f}, '
                        f'Comm: {order.executed.comm:.2f}')
            else:
                self.log(f'SELL EXECUTED, Price: {order.executed.price:.2f}, '
                        f'Cost: {order.executed.value:.2f}, '
                        f'Comm: {order.executed.comm:.2f}')
    
    def stop(self):
        """Вывод финальной статистики"""
        super().stop()
        final_value = self.broker.getvalue()
        total_return = (final_value / self.broker.startingcash - 1) * 100
        self.log(f'Final Portfolio Value: {final_value:.2f}')
        self.log(f'Total Return: {total_return:.2f}%')
        
        # Расчет годовой доходности (приблизительно)
        trading_days = len(self.data)
        years = trading_days / 252
        if years > 0:
            annual_return = ((1 + total_return / 100) ** (1 / years) - 1) * 100
            self.log(f'Annualized Return: {annual_return:.2f}%')


class SMABollingerBands(Strategy):
    """
    Комбинированная стратегия: SMA + Bollinger Bands
    Использует пересечение SMA для определения тренда и Bollinger Bands для точек входа
    """
    params = (
        ('sma_period', 30),
        ('bb_period', 20),
        ('bb_dev', 2.0),
        ('position_size', 0.1),
        ('stop_loss_percent', 4.0),
        ('take_profit_percent', 12.0),
    )
    
    def __init__(self):
        super().__init__()
        self.sma = bt.indicators.SMA(self.datas[0].close, period=self.params.sma_period)
        self.bb = bt.indicators.BollingerBands(self.datas[0].close, 
                                               period=self.params.bb_period,
                                               devfactor=self.params.bb_dev)
        
    def next(self):
        super().next()
        
        if len(self.data) < self.params.sma_period:
            return
        
        if not self.position:
            # Покупка: цена выше SMA и касается нижней полосы Bollinger
            if (self.data.close[0] > self.sma[0] and 
                self.data.close[0] <= self.bb.lines.bot[0] * 1.01):
                
                size = (self.broker.get_cash() * self.params.position_size) / self.data.close[0]
                self.buy(size=size)
                self.log(f'BUY - Price: {self.data.close[0]:.2f}, '
                        f'SMA: {self.sma[0]:.2f}, '
                        f'BB Lower: {self.bb.lines.bot[0]:.2f}')
        
        elif self.position:
            entry_price = self.position.price
            current_price = self.data.close[0]
            profit_percent = (current_price - entry_price) / entry_price * 100
            
            # Выход по тейк-профиту или стоп-лоссу
            if profit_percent >= self.params.take_profit_percent:
                self.close()
                self.log(f'Take profit: {profit_percent:.2f}%')
            elif profit_percent <= -self.params.stop_loss_percent:
                self.close()
                self.log(f'Stop loss: {profit_percent:.2f}%')
            # Выход при достижении верхней полосы Bollinger
            elif current_price >= self.bb.lines.top[0]:
                self.close()
                self.log(f'Exit at BB upper: {current_price:.2f}')


if __name__ == '__main__':
    print("=" * 70)
    print("TESTING ENHANCED SMA STRATEGY ON MULTIPLE TICKERS")
    print("=" * 70)
    
    tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
    
    # Тестирование улучшенной стратегии на нескольких тикерах
    results = run_on_multiple_tickers(
        strategy_class=EnhancedSMA,
        tickers=tickers,
        interval='1d',
        start_date='01.01.21',
        end_date='01.03.25',
        log_orders=False,
        plot=False,
        copy_to_clipboard=True,
        # Параметры стратегии
        fast_sma_period=10,
        middle_sma_period=30,
        slow_sma_period=50,
        position_size=0.1,
        use_trailing_stop=True,
        trailing_stop_percent=5.0,
        take_profit_percent=15.0,
        stop_loss_percent=5.0
    )
    
    print("\n" + "=" * 70)
    print("TESTING SMA + BOLLINGER BANDS STRATEGY")
    print("=" * 70)
    
    # Тестирование комбинированной стратегии
    results_bb = run_on_multiple_tickers(
        strategy_class=SMABollingerBands,
        tickers=["AAPL"],
        interval='1d',
        start_date='01.01.21',
        end_date='01.03.25',
        log_orders=False,
        plot=True,
        copy_to_clipboard=False,
        sma_period=30,
        bb_period=20,
        bb_dev=2.0,
        position_size=0.1
    )
    
    print("\n" + "=" * 70)
    print("OPTIMIZATION EXAMPLE (commented)")
    print("=" * 70)
    """
    # Пример оптимизации параметров
    optimization_params = {
        'fast_sma_period': range(5, 20, 2),
        'middle_sma_period': range(20, 40, 5),
        'slow_sma_period': range(40, 60, 5),
        'position_size': [0.05, 0.1, 0.15],
        'trailing_stop_percent': [3, 5, 7],
        'take_profit_percent': [10, 15, 20],
        'stop_loss_percent': [3, 5, 7],
    }
    
    simple_optimization(
        strategy_class=EnhancedSMA,
        ticker='AAPL',
        interval='1d',
        start_date='01.01.21',
        end_date='01.03.25',
        optimization_params=optimization_params,
        optimization_method='grid'
    )
    """