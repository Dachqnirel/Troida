import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run
from backtesting.optimization import simple_optimization
import numpy as np


class EnhancedRSI(Strategy):
    """
    Улучшенная RSI стратегия с дополнительными фильтрами:
    - Трендовый фильтр на основе скользящих средних
    - Динамические уровни RSI в зависимости от волатильности
    - Частичное закрытие позиции
    - Трейлинг-стоп
    - Фильтр по объему
    """
    params = (
        # RSI параметры
        ('rsi_period', 14),
        ('rsi_overbought', 70),
        ('rsi_oversold', 30),
        ('rsi_dynamic', True),  # Использовать динамические уровни
        
        # Трендовые фильтры
        ('use_trend_filter', True),
        ('ma_fast', 20),
        ('ma_slow', 50),
        
        # Фильтр волатильности
        ('use_volatility_filter', True),
        ('atr_period', 14),
        ('volatility_threshold', 1.5),  # ATR выше среднего в X раз
        
        # Фильтр объема
        ('use_volume_filter', True),
        ('volume_ma_period', 20),
        ('volume_threshold', 1.2),  # Объем выше среднего в X раз
        
        # Управление позицией
        ('position_size', 0.1),  # 10% от капитала на сделку
        ('use_partial_exit', True),
        ('partial_exit_ratio', 0.5),  # Закрывать 50% позиции при первом сигнале
        
        # Трейлинг-стоп
        ('use_trailing_stop', True),
        ('trailing_stop_percent', 5.0),  # 5% трейлинг-стоп
        
        # Тейк-профит
        ('take_profit_percent', 15.0),
        
        # Фильтр по времени (опционально)
        ('trading_hours_only', False),  # Только в торговые часы (для внутридневной торговли)
    )
    
    def __init__(self):
        super().__init__()
        
        # Основной RSI
        self.rsi = bt.indicators.RSI(self.datas[0], period=self.params.rsi_period)
        
        # Динамические уровни RSI (скользящие экстремумы)
        if self.params.rsi_dynamic:
            self.rsi_max = bt.indicators.Highest(self.rsi, period=50)
            self.rsi_min = bt.indicators.Lowest(self.rsi, period=50)
        
        # Трендовые индикаторы
        if self.params.use_trend_filter:
            self.ma_fast = bt.indicators.SMA(self.datas[0].close, period=self.params.ma_fast)
            self.ma_slow = bt.indicators.SMA(self.datas[0].close, period=self.params.ma_slow)
        
        # Индикатор волатильности
        if self.params.use_volatility_filter:
            self.atr = bt.indicators.ATR(self.datas[0], period=self.params.atr_period)
            self.atr_ma = bt.indicators.SMA(self.atr, period=self.params.atr_period * 2)
        
        # Индикатор объема
        if self.params.use_volume_filter and hasattr(self.datas[0], 'volume'):
            self.volume_ma = bt.indicators.SMA(self.datas[0].volume, period=self.params.volume_ma_period)
        
        # Для отслеживания стоп-лосса
        self.trailing_stop_price = None
        self.entry_price = None
        self.position_size_initial = None
        
    def get_dynamic_rsi_levels(self):
        """Получить динамические уровни RSI"""
        if self.params.rsi_dynamic and len(self.rsi_min) > 0 and len(self.rsi_max) > 0:
            oversold = self.rsi_min[0] + (self.rsi_max[0] - self.rsi_min[0]) * 0.2
            overbought = self.rsi_max[0] - (self.rsi_max[0] - self.rsi_min[0]) * 0.2
            return oversold, overbought
        return self.params.rsi_oversold, self.params.rsi_overbought
    
    def is_bullish_trend(self):
        """Проверка восходящего тренда"""
        if not self.params.use_trend_filter:
            return True
        return self.ma_fast[0] > self.ma_slow[0]
    
    def is_volume_high(self):
        """Проверка высокого объема"""
        if not self.params.use_volume_filter or not hasattr(self.datas[0], 'volume'):
            return True
        if self.volume_ma[0] > 0:
            return self.datas[0].volume[0] > self.volume_ma[0] * self.params.volume_threshold
        return True
    
    def is_volatility_normal(self):
        """Проверка нормальной волатильности (не экстремально высокой)"""
        if not self.params.use_volatility_filter:
            return True
        if self.atr_ma[0] > 0:
            return self.atr[0] <= self.atr_ma[0] * self.params.volatility_threshold
        return True
    
    def calculate_trade_size(self):
        """Расчет размера позиции с учетом риска"""
        cash = self.broker.get_cash()
        # Используем процент от капитала
        size = (cash * self.params.position_size) / self.data.close[0]
        return size
    
    def update_trailing_stop(self):
        """Обновление трейлинг-стопа"""
        if self.position and self.params.use_trailing_stop and self.entry_price:
            current_price = self.data.close[0]
            new_stop = current_price * (1 - self.params.trailing_stop_percent / 100)
            
            if self.trailing_stop_price is None or new_stop > self.trailing_stop_price:
                self.trailing_stop_price = new_stop
                self.log(f'Trailing stop updated to {self.trailing_stop_price:.2f}')
            
            # Проверка на срабатывание стоп-лосса
            if current_price <= self.trailing_stop_price:
                self.log(f'Trailing stop triggered at {current_price:.2f}')
                self.close()
                self.trailing_stop_price = None
                self.entry_price = None
    
    def check_take_profit(self):
        """Проверка тейк-профита"""
        if self.position and self.entry_price:
            current_price = self.data.close[0]
            profit_percent = (current_price - self.entry_price) / self.entry_price * 100
            
            if profit_percent >= self.params.take_profit_percent:
                self.log(f'Take profit triggered: {profit_percent:.2f}%')
                self.close()
                return True
        return False
    
    def next(self):
        super().next()
        
        # Проверка достаточности данных
        if len(self.datas[0]) < max(self.params.ma_slow, self.params.rsi_period):
            return
        
        # Получаем динамические уровни RSI
        oversold, overbought = self.get_dynamic_rsi_levels()
        
        # Обновляем трейлинг-стоп для открытой позиции
        if self.position:
            self.update_trailing_stop()
            
            # Частичное закрытие позиции
            if (self.params.use_partial_exit and 
                self.position.size == self.position_size_initial and 
                self.rsi[0] > overbought * 0.8):  # При приближении к перекупленности
                
                close_size = int(self.position.size * self.params.partial_exit_ratio)
                if close_size > 0:
                    self.sell(size=close_size)
                    self.log(f'Partial exit: closed {close_size} units, RSI: {self.rsi[0]:.2f}')
            
            # Проверка тейк-профита
            self.check_take_profit()
        
        # Поиск сигналов на вход
        if not self.position:
            # Комплексные условия для входа
            buy_signal = False
            
            # Основной сигнал RSI
            rsi_signal = self.rsi[0] < oversold
            
            # Дополнительные фильтры
            trend_ok = self.is_bullish_trend()
            volume_ok = self.is_volume_high()
            volatility_ok = self.is_volatility_normal()
            
            # Контр-трендовый сигнал (для дивергенций)
            if rsi_signal and trend_ok and volume_ok and volatility_ok:
                buy_signal = True
                self.log(f'BUY SIGNAL - RSI: {self.rsi[0]:.2f}, '
                        f'oversold: {oversold:.2f}, '
                        f'trend: {trend_ok}, '
                        f'volume: {volume_ok}')
            
            # Альтернативный сигнал: дивергенция цены и RSI
            if len(self.rsi) > 20 and not buy_signal:
                # Проверяем, не было ли более низкого минимума цены при более высоком минимуме RSI
                price_low = min(self.data.close.get(size=20))
                rsi_low = min(self.rsi.get(size=20))
                
                if self.data.close[0] <= price_low * 1.01 and self.rsi[0] > rsi_low * 1.05:
                    buy_signal = True
                    self.log(f'DIVERGENCE BUY SIGNAL - Price low but RSI rising')
            
            if buy_signal:
                size = self.calculate_trade_size()
                self.buy(size=size)
                self.entry_price = self.data.close[0]
                self.position_size_initial = size
                self.trailing_stop_price = None
                self.log(f'BUY executed: size={size:.2f}, price={self.data.close[0]:.2f}')
        
        # Сигналы на выход (если нет стоп-лосса/тейк-профита)
        elif not self.check_take_profit():
            # Выход при перекупленности
            if self.rsi[0] > overbought:
                self.log(f'SELL SIGNAL - RSI: {self.rsi[0]:.2f}, overbought: {overbought:.2f}')
                self.close()
                self.entry_price = None
                self.position_size_initial = None
                self.trailing_stop_price = None
    
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
        self.log(f'Final Portfolio Value: {self.broker.getvalue():.2f}')
        self.log(f'Total Return: {(self.broker.getvalue() / self.broker.startingcash - 1) * 100:.2f}%')


class RSIDivergenceStrategy(Strategy):
    """
    Расширенная стратегия с фокусом на дивергенции RSI
    """
    params = (
        ('rsi_period', 14),
        ('divergence_lookback', 20),
        ('min_divergence_strength', 0.05),  # Минимальная сила дивергенции
        ('position_size', 0.1),
        ('stop_loss_percent', 3.0),
        ('take_profit_percent', 12.0),
    )
    
    def __init__(self):
        super().__init__()
        self.rsi = bt.indicators.RSI(self.datas[0], period=self.params.rsi_period)
        self.divergence_buy = False
        self.divergence_sell = False
        
    def detect_divergence(self):
        """Детектирование дивергенций"""
        if len(self.data) < self.params.divergence_lookback + 1:
            return False, False
        
        # Ищем минимумы цены и RSI
        price_lows = []
        rsi_lows = []
        
        for i in range(1, self.params.divergence_lookback + 1):
            if self.data.close[-i] <= self.data.close[-i-1]:
                price_lows.append((self.data.close[-i], -i))
            if self.rsi[-i] <= self.rsi[-i-1]:
                rsi_lows.append((self.rsi[-i], -i))
        
        if len(price_lows) >= 2 and len(rsi_lows) >= 2:
            # Бычья дивергенция: цена делает более низкий минимум, а RSI более высокий
            recent_price_low = min(price_lows, key=lambda x: x[0])
            prev_price_low = min([x for x in price_lows if x[1] < recent_price_low[1]], 
                                key=lambda x: x[0], default=None)
            
            recent_rsi_low = min(rsi_lows, key=lambda x: x[0])
            prev_rsi_low = min([x for x in rsi_lows if x[1] < recent_rsi_low[1]],
                              key=lambda x: x[0], default=None)
            
            if prev_price_low and prev_rsi_low:
                price_lower = recent_price_low[0] < prev_price_low[0]
                rsi_higher = recent_rsi_low[0] > prev_rsi_low[0]
                
                if price_lower and rsi_higher:
                    divergence_strength = (prev_rsi_low[0] - recent_rsi_low[0]) / prev_rsi_low[0]
                    if divergence_strength > self.params.min_divergence_strength:
                        return True, False  # Бычья дивергенция
        
        return False, False
    
    def next(self):
        super().next()
        
        if len(self.data) < self.params.divergence_lookback:
            return
        
        buy_div, sell_div = self.detect_divergence()
        
        if not self.position:
            if buy_div or self.rsi[0] < 30:
                size = (self.broker.get_cash() * self.params.position_size) / self.data.close[0]
                self.buy(size=size)
                self.log(f'BUY - Divergence: {buy_div}, RSI: {self.rsi[0]:.2f}')
        
        elif self.position:
            # Выход по стоп-лоссу или тейк-профиту
            entry_price = self.position.price
            current_price = self.data.close[0]
            profit_percent = (current_price - entry_price) / entry_price * 100
            
            if profit_percent >= self.params.take_profit_percent:
                self.close()
                self.log(f'Take profit: {profit_percent:.2f}%')
            elif profit_percent <= -self.params.stop_loss_percent:
                self.close()
                self.log(f'Stop loss: {profit_percent:.2f}%')
            elif self.rsi[0] > 70 or sell_div:
                self.close()
                self.log(f'SELL - RSI: {self.rsi[0]:.2f}, Divergence: {sell_div}')


if __name__ == '__main__':
    # Тестирование улучшенной стратегии
    print("=" * 60)
    print("Testing Enhanced RSI Strategy")
    print("=" * 60)
    
    strategy = simple_run(
        strategy_class=EnhancedRSI,
        ticker='TSLA',
        interval='1d',
        start_date="01.01.21",
        end_date="28.03.25",
        log_orders=False,
        # Параметры для оптимизации можно передать здесь
    )
    
    print("\n" + "=" * 60)
    print("Testing RSI Divergence Strategy")
    print("=" * 60)
    
    # Тестирование стратегии на дивергенциях
    strategy_div = simple_run(
        strategy_class=RSIDivergenceStrategy,
        ticker='TSLA',
        interval='1d',
        start_date="01.01.21",
        end_date="28.03.25",
        log_orders=False,
    )
    
    # Сравнение стратегий
    from backtesting.strategy_visualization import compare_price_pnl
    # Раскомментируйте для визуализации
    # compare_price_pnl(strategy, window_days=300)