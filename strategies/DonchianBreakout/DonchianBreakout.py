import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run

class Donchian(bt.Indicator):
    """
    Donchian Channels: High/Low за последние N баров.
    """
    lines = ('upper', 'lower', 'mid',)
    params = (('period', 20),)

    def init(self):
        p = self.p.period
        self.addminperiod(p)  # дождаться накопления p баров
        hh = bt.ind.Highest(self.data.high, period=p)
        ll = bt.ind.Lowest(self.data.low, period=p)
        self.l.upper = hh
        self.l.lower = ll
        self.l.mid = (hh + ll) / 2.0

class DonchianBreakout(Strategy):
    """
    Пробойная логика:
    - Вход long: Close > Upper(N) предыдущего бара
    - Выход: Close < Lower(N) предыдущего бара
    """
    params = dict(
        period=20,          # окно Donchian
        risk_fraction=0.2,  # доля кэша на сделку
        log_orders=True,
    )

    def init(self):
        self.dc = Donchian(self.data, period=self.p.period)

    def log(self, txt, dt=None):
        # учитываем флаг логирования из params
        if not self.p.log_orders:
            return
        super().log(txt, dt)

    def _calc_size(self, fraction=0.2):
        cash = self.broker.getcash()
        price = float(self.data.close[0])
        if price <= 0:
            return 0.0
        size = (cash * float(fraction)) / price
        return max(0.0, size)

    def next(self):
        super().next()

        # ждём, пока индикатор будет валиден
        if len(self.data) < self.p.period:
            return

        c = float(self.data.close[0])
        up_prev = float(self.dc.upper[-1])
        low_prev = float(self.dc.lower[-1])

        # вход
        if not self.position and c > up_prev:
            size = self._calc_size(self.p.risk_fraction)
            self.log(f"BUY SIGNAL: close={c:.2f} > upper_prev={up_prev:.2f}, size={size:.2f}")
            if size > 0:
                self.buy(size=size)
            return

        # выход
        if self.position and c < low_prev:
            self.log(f"EXIT SIGNAL: close={c:.2f} < lower_prev={low_prev:.2f}")
            self.close()

if __name__ == '__main__':
    simple_run(
        DonchianBreakout,
        ticker='AAPL',
        interval='1d',
        start_date='01.01.21',
        end_date='01.03.25',
        initial_cash=100000,
        commission=0.0005,
        copy_to_clipboard=True,
        log_orders=False,
        period=20,
        risk_fraction=0.2
    )