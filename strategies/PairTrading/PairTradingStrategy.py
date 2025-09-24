import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run
from backtesting.optimization import simple_optimization
import numpy as np


class PairTradingStrategy(Strategy):
    """
    Стратегия парного трейдинга на основе корреляции двух тикеров.
    Покупаем отстающий актив и продаем опережающий при расхождении,
    закрываем позиции при схождении.
    """
    params = (
        ('lookback_period', 30),  # Период для расчета корреляции и z-score
        ('entry_threshold', 1.0),  # Порог входа в сделку (стандартные отклонения)
        ('exit_threshold', 0.5),  # Порог выхода из сделки
        ('position_size', 0.05),  # Размер позиции (5% от капитала)
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Проверяем наличие двух тикеров
        if len(self.datas) < 2:
            raise ValueError("Strategy requires exactly 2 data feeds")

        self.data0 = self.datas[0]  # Первый тикер (например, PEP)
        self.data1 = self.datas[1]  # Второй тикер (например, KO)

        # Для хранения истории цен
        self.price_history0 = []
        self.price_history1 = []

        # Для хранения спреда и z-score
        self.spread = []
        self.zscore = []

        # Для отслеживания позиций
        self.entry_prices = {self.data0._name: None, self.data1._name: None}
        self.in_position = False
        self.entry_z = 0

    def notify_order(self, order):
        """Обработчик ордеров для парного трейдинга"""
        if order.status in [order.Submitted, order.Accepted]:
            self.log(f'ORDER {order.Status[order.status]}')
            return

        if order.status == order.Completed:
            if order.isbuy():
                # Обработка покупки
                self.entry_prices[order.data._name] = order.executed.price
                position_value = order.executed.size * order.executed.price
                self.log(
                    f'BUY EXECUTED {order.data._name}, Price: {order.executed.price:.2f}, Value: {position_value:.2f}')

            elif order.issell():
                # Обработка продажи
                sell_price = order.executed.price
                position_value = order.executed.size * sell_price
                entry_price = self.entry_prices[order.data._name]

                if entry_price is not None:
                    profit_percentage = ((sell_price - entry_price) / entry_price) * 100
                    self.log(
                        f'SELL EXECUTED {order.data._name}, Price: {sell_price:.2f}, Value: {position_value:.2f}, Profit: {profit_percentage:.2f}%')

                    if profit_percentage > 0:
                        self.won_trade_profits.append(profit_percentage)
                    else:
                        self.lost_trade_profits.append(profit_percentage)

                    self.entry_prices[order.data._name] = None

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'ORDER {order.Status[order.status]}')

    def next(self):
        """Логика принятия торговых решений"""
        super().next()

        # Собираем историю цен
        self.price_history0.append(self.data0.close[0])
        self.price_history1.append(self.data1.close[0])

        # Убедимся, что у нас достаточно данных
        if len(self.price_history0) < self.params.lookback_period:
            return

        self.price_history0 = self.price_history0[-self.params.lookback_period:]
        self.price_history1 = self.price_history1[-self.params.lookback_period:]

        # Рассчитываем спред (разница нормализованных цен)
        norm0 = np.array(self.price_history0) / np.mean(self.price_history0)
        norm1 = np.array(self.price_history1) / np.mean(self.price_history1)
        current_spread = norm0[-1] - norm1[-1]
        self.spread.append(current_spread)
        self.spread = self.spread[-self.params.lookback_period:]

        # Рассчитываем z-score спреда
        if len(self.spread) >= 2:
            mean_spread = np.mean(self.spread)
            std_spread = np.std(self.spread)

            if std_spread != 0:
                current_z = (current_spread - mean_spread) / std_spread
                self.zscore.append(current_z)

                # Логируем текущий z-score
                self.log(f'Current z-score: {current_z:.2f}')

                # Логика входа и выхода
                if not self.in_position:
                    if current_z > self.params.entry_threshold:
                        # data0 перекуплен относительно data1
                        self.sell(data=self.data0, size=self.calculate_trade_size(self.data0))
                        self.buy(data=self.data1, size=self.calculate_trade_size(self.data1))
                        self.in_position = True
                        self.entry_z = current_z
                        self.log(f'SHORT {self.data0._name} / LONG {self.data1._name} at z-score: {current_z:.2f}')

                    elif current_z < -self.params.entry_threshold:
                        # data0 перепродан относительно data1
                        self.buy(data=self.data0, size=self.calculate_trade_size(self.data0))
                        self.sell(data=self.data1, size=self.calculate_trade_size(self.data1))
                        self.in_position = True
                        self.entry_z = current_z
                        self.log(f'LONG {self.data0._name} / SHORT {self.data1._name} at z-score: {current_z:.2f}')

                else:
                    # Проверяем условия выхода
                    exit_condition = (abs(current_z) < self.params.exit_threshold)  # Схождение

                    if exit_condition:
                        self.close(data=self.data0)
                        self.close(data=self.data1)
                        self.in_position = False
                        self.log(f'Exit position at z-score: {current_z:.2f}')

    def calculate_trade_size(self, data):
        """Рассчитываем размер позиции как % от капитала"""
        cash = self.broker.get_cash()
        size = (cash * self.params.position_size) / data.close[0]
        return size

    def stop(self):
        """Вызывается по окончании тестирования"""
        super().stop()
        # Принудительно закрываем все позиции в конце
        if self.in_position:
            self.close(data=self.data0)
            self.close(data=self.data1)

if __name__ == '__main__':
    strategy = simple_run(
        strategy_class=PairTradingStrategy,
        ticker=['PEP', 'AAPL'],  # Список из двух тикеров
        interval='1d',
        start_date="01.01.20",
        end_date="01.06.22",
        log_orders=True,
        lookback_period=30,
        entry_threshold=1.0,
        exit_threshold=0.5,
        position_size=0.05
    )