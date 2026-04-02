import backtrader as bt
from backtesting.strategy_template import Strategy, simple_run


class Donchian(bt.Indicator):
    """
    Donchian Channels: High/Low за последние N баров.
    """
    lines = ('upper', 'lower', 'mid',)
    params = (('period', 20),)

    def __init__(self):
        super().__init__()
        p = self.p.period
        self.addminperiod(p)  # дождаться накопления p баров
        hh = bt.ind.Highest(self.data.high, period=p)
        ll = bt.ind.Lowest(self.data.low, period=p)
        self.l.upper = hh
        self.l.lower = ll
        self.l.mid = (hh + ll) / 2.0

class DonchianBreakout(Strategy):
    """
    Улучшенная пробойная логика:
    - Вход long: пробой верхней границы канала с ATR-буфером в сторону тренда.
    - Выход: уход ниже средней линии канала или по защитному стопу.
    """
    params = dict(
        period=20,
        trend_sma_period=50,
        atr_period=14,
        breakout_atr_buffer=0.2,
        risk_per_trade=0.01,
        max_position_fraction=0.25,
        atr_stop_multiplier=2.0,
        atr_trail_multiplier=1.3,
        log_orders=True,
    )

    def __init__(self):
        super().__init__()
        self.dc = Donchian(self.data, period=self.p.period)
        self.trend_sma = bt.indicators.SMA(
            self.data.close,
            period=self.p.trend_sma_period
        )
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.entry_price = None
        self.highest_price = None
        self.stop_price = None

    def log(self, txt, dt=None):
        # учитываем флаг логирования из params
        if not self.p.log_orders:
            return
        super().log(txt, dt)

    def notify_order(self, order):
        super().notify_order(order)

        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if self.position.size > 0:
                self.entry_price = order.executed.price
                self.highest_price = order.executed.price
                self.stop_price = (
                    order.executed.price
                    - float(self.atr[0]) * self.p.atr_stop_multiplier
                )
            else:
                self.entry_price = None
                self.highest_price = None
                self.stop_price = None
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(
                f'TRADE CLOSED: GROSS PnL {trade.pnl:.2f}, '
                f'NET PnL {trade.pnlcomm:.2f}'
            )

    def _calc_size(self, price, atr):
        cash = self.broker.getcash()
        stop_distance = atr * self.p.atr_stop_multiplier
        if price <= 0 or stop_distance <= 0:
            return 0.0
        size_by_risk = (cash * self.p.risk_per_trade) / stop_distance
        size_by_cap = (cash * self.p.max_position_fraction) / price
        return max(0.0, min(size_by_risk, size_by_cap))

    def next(self):
        super().next()

        if self.order:
            return

        # ждём, пока индикатор будет валиден
        if len(self.data) < max(self.p.period, self.p.trend_sma_period):
            return

        c = float(self.data.close[0])
        up_prev = float(self.dc.upper[-1])
        low_prev = float(self.dc.lower[-1])
        mid_prev = float(self.dc.mid[-1])
        atr = float(self.atr[0])
        trend_ok = (
            c > self.trend_sma[0]
            and self.trend_sma[0] > self.trend_sma[-1]
        )
        breakout_level = up_prev + atr * self.p.breakout_atr_buffer

        if not self.position and trend_ok and c > breakout_level:
            size = self._calc_size(c, atr)
            self.log(
                f'BUY SIGNAL: close={c:.2f} > breakout={breakout_level:.2f}, '
                f'size={size:.2f}'
            )
            if size > 0:
                self.order = self.buy(size=size)
            return

        if self.position:
            self.highest_price = max(self.highest_price, c)
            trailing_stop = self.highest_price - atr * self.p.atr_trail_multiplier
            self.stop_price = max(self.stop_price, trailing_stop)

            exit_by_channel = c < mid_prev and c < low_prev + atr
            exit_by_stop = c <= self.stop_price

            if exit_by_channel or exit_by_stop:
                reason = 'channel' if exit_by_channel else 'stop'
                self.log(f'EXIT SIGNAL by {reason}: close={c:.2f}')
                self.order = self.close()

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
        trend_sma_period=50,
        atr_period=14,
        breakout_atr_buffer=0.2,
        risk_per_trade=0.01,
        max_position_fraction=0.25,
        atr_stop_multiplier=2.0,
        atr_trail_multiplier=1.3,
    )
