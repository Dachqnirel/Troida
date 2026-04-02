import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run


class BollingerBreakoutOptimized(Strategy):
    params = (
        ('bollinger_period', 10),  # период расчёта средней и стандартного отклонения
        ('devfactor', 1.5),        # множитель стандартного отклонения
        ('risk_pct', 0.30),        # доля свободного капитала на одну покупку (30 %)
    )

    def __init__(self) -> None:
        super().__init__()
        # Индикатор BollingerBands возвращает линии top, mid, bot
        self.bb = bt.indicators.BollingerBands(
            self.datas[0],
            period=self.params.bollinger_period,
            devfactor=self.params.devfactor
        )

    def next(self) -> None:
        super().next()
        close_price = self.data.close[0]
        top_band = self.bb.lines.top[0]
        bot_band = self.bb.lines.bot[0]

        # Сигнал на покупку: цена закрытия выше верхней полосы
        if close_price > top_band:
            self.log(f'BUY SIGNAL at: {close_price:.2f}')
            # Покупаем на фиксированную долю капитала
            self.buy(size=self.calculate_trade_size())

        # Сигнал на продажу: цена закрытия ниже нижней полосы
        elif close_price < bot_band:
            self.log(f'SELL SIGNAL at: {close_price:.2f}')
            # Закрываем все позиции, если они есть
            if self.position.size > 0:
                self.close()

    def calculate_trade_size(self) -> float:
        """Рассчитывает количество акций для покупки в зависимости от свободного капитала.

        Возвращает: количество акций (может быть дробным) на основе
        ``risk_pct`` и текущей цены.
        """
        cash = self.broker.get_cash()
        size = (cash * self.params.risk_pct) / self.data.close[0]
        return size

    def stop(self) -> None:
        super().stop()


if __name__ == '__main__':
    strategy, results = simple_run(
        strategy_class=BollingerBreakoutOptimized,
        ticker='AAPL',
        interval='1d',
        start_date='01.01.21',
        end_date='28.03.25',
        initial_cash=10_000,
        commission=0.0005,
        log_orders=False,
        plot=True
    )