
import backtrader as bt
from strategy_template import Strategy, simple_run
from optimization import simple_optimization


class DynamicSMAStrategy(Strategy):
    """
    Стратегия на основе скользящих средних (SMA) с динамической регулировкой объёма позиций.
    Количество акций определяется исходя из уровня волатильности рынка (ATR).
    Покупка осуществляется при пересечении быстрой SMA медленной SMA снизу вверх.
    Продажа производится при обратном сигнале.
    Рискуем лишь фиксированным процентом капитала (например, 3%) на каждую сделку.
    """
    
    params = (
        ('fast_sma_period', 7),
        ('slow_sma_period', 30),
        ('atr_period', 14), # Период усреднения для вычисления ATR
        ('risk_percentage', 0.03), # Процент риска на одну сделку
    )

    def __init__(self):
        super().__init__()
        
        # Вычисляем индикаторы
        self.sma_fast = bt.indicators.SMA(self.datas[0], period=self.p.fast_sma_period)
        self.sma_slow = bt.indicators.SMA(self.datas[0], period=self.p.slow_sma_period)
        self.atr = bt.indicators.ATR(self.datas[0], period=self.p.atr_period)
        
        # Сигнал пересечения MA
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)

    def notify_order(self, order):
        super().notify_order(order)

    def next(self):
        super().next()
        
        # Проверяем сигналы кроссовера
        if self.crossover > 0:
            self.log('BUY SIGNAL')
            trade_size = self.calculate_trade_size()
            self.buy(size=trade_size)
            
        elif self.crossover < 0:
            self.log('SELL SIGNAL')
            if self.position.size > 0:
                self.close()
                
    def calculate_trade_size(self):
        """Рассчитываем количество акций для торговли."""
        cash = self.broker.get_cash()   # Доступная наличность
        atr_value = self.atr[0]          # Текущее значение ATR
        risk_amount = cash * self.p.risk_percentage     # Фиксированная сумма риска
        price = self.data.close[0]      # Текущая цена закрытия акции
        
        # Расчёт размера позиции исходя из ATR и желаемого процента риска
        position_size = int(risk_amount // atr_value)
        
        # Ограничиваем позицию доступностью денежных средств
        max_position = cash // price
        actual_position = min(position_size, max_position)
        
        return actual_position

    def stop(self):
        super().stop()


# Тестирование стратегии
if __name__ == '__main__':
    simple_optimization(
        strategy_class=DynamicSMAStrategy,
        ticker='AAPL',
        interval='1d',
        in_sample_start_date='01.01.21',
        in_sample_end_date='01.06.24',
        out_of_sample_start_date='02.06.24',
        out_of_sample_end_date='28.03.25',
        fast_sma_period=range(5, 15),  # Диапазон периодов для быстрого SMA
        slow_sma_period=range(20, 40), # Диапазон периодов для медленного SMA
        atr_period=(14,)               # Периоды для ATR
    )
  
