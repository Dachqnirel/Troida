import backtrader as bt
from backtesting.historical_data_access import get_ticker_dataframe
from backtesting.custom_analyzers import KellyCriterionAnalyzer, SortinoRatioAnalyzer, CustomAnalyzer
import pyperclip
from backtesting.strategy_visualization import save_strategy_plots


class Strategy(bt.Strategy):
    params = (('log_orders', True),)

    def __init__(self, **kwargs):
        if 'log_orders' in kwargs:
            self.params.log_orders = kwargs['log_orders']

    def __init__(self):
        pass

    def notify_trade(self, trade):
        pass

    def log(self, txt, dt=None):
        if self.params.log_orders:
            dt = dt or self.datas[0].datetime.datetime(0)
            dt_str = dt.strftime('%d.%m.%y %H:%M:%S')
            print(f'{dt_str} {txt}')

    def notify_order(self, order):
        if order.status == order.Completed:
            execution_type = order.getordername()
            execution_price = order.executed.price
            execution_size = order.executed.size
            execution_value = order.executed.value
            execution_comm = order.executed.comm
            
            
            if order.isbuy():
                self.log(f'BUY EXECUTED at {execution_price:.2f}, type={execution_type}, id = {order.ref}')
            elif order.issell():
                self.log(f'SELL EXECUTED at {execution_price:.2f}, type={execution_type}, id = {order.ref}')

        elif order.status in [order.Submitted, order.Accepted, order.Canceled, order.Margin, order.Rejected]:
            self.log(f'ORDER {order.Status[order.status]}, type={order.getordername()}, id = {order.ref}')
            pass


def simple_run(strategy_class, ticker, interval, start_date, end_date, initial_cash=10_000,
               commission=0.0, plot=True, copy_to_clipboard=False, save_plots=False,
               log_orders=False, **params):
    """
    Запускает обычное тестирование стратегии на заданном промежутке времени
    :param strategy_class: класс стратегии
    :param ticker: тикер
    :param interval: интервал
    :param start_date: дата начала тестирования
    :param end_date: дата конца тестирования
    :param initial_cash: начальный капитал
    :param commission: комиссия
    :param plot: нужно ли выводить графики
    :param copy_to_clipboard: нужно ли копировать результаты тестирования в буфер обмена
    :param save_plots: нужно ли сохранять графики в папку стратегии
    :param log_orders: нужно ли логировать ордера
    :param params: параметры стратегии - например fast_sma_period=5, slow_sma_period=10
    :return: объект Strategy и список параметров
    """
    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_class, log_orders=log_orders, **params)

    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)

    dataframe = get_ticker_dataframe(ticker, interval, start_date, end_date)
    dataframe = bt.feeds.PandasData(dataname=dataframe)
    cerebro.adddata(dataframe)


    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='TradeAnalyzer')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='SharpeRatio', annualize=True)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='Returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='DrawDown')
    # cerebro.addanalyzer(KellyCriterionAnalyzer, _name='Kelly')
    # cerebro.addanalyzer(SortinoRatioAnalyzer, _name="Sortino")
    cerebro.addanalyzer(CustomAnalyzer, _name="CustomAnalyzer")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='TimeReturn')

    strategy = cerebro.run()[0]

    trades_analysis = strategy.analyzers.TradeAnalyzer.get_analysis()
    sharpe_ratio = strategy.analyzers.SharpeRatio.get_analysis()
    returns = strategy.analyzers.Returns.get_analysis()
    draw_down = strategy.analyzers.DrawDown.get_analysis()
    # kelly = strategy.analyzers.Kelly.get_analysis()
    # sortino = strategy.analyzers.Sortino.get_analysis()
    custom_analyzer = strategy.analyzers.CustomAnalyzer.get_analysis()
    time_return = strategy.analyzers.TimeReturn.get_analysis()


    parameters = [
        ("Название стратегии", strategy_class.__name__),
        ("Параметры стратегии", ", ".join(f"{key} = {val}" for key, val in params.items())),
        ("Тикер", f"{ticker}"),
        ("Дата начала тестирования", start_date),
        ("Дата конца тестирования", end_date),
        ("Интервал тестирования", interval),
        ("Средняя доходность в год в %", f"{returns['rnorm100']:.2f}"),
        ("Доходность за весь период в %", f"{returns['rtot'] * 100:.2f}"),
        ("Средняя доходность 'купи и держи' за весь период в %", f"{custom_analyzer['buy_and_hold_profit']:.2f}"),
        ("На сколько % лучше стратегия, чем купить и держать", f"{returns['rnorm100'] - custom_analyzer['buy_and_hold_profit']:.2f}"),
        ("Коэффициент Шарпа", f"{sharpe_ratio['sharperatio']:.2f}"),
        ("Критерий Келли", "-"), # ("Критерий Келли", f"{kelly['Kelly Criterion']}"), # TODO: ошибка при делении на ноль
        ("Коэффициент Сортино", "-"), # ("Коэффициент Сортино", f"{sortino['Sortino Ratio']:.2f}"), # TODO: неправильно считает
        ("Максимальная просадка в %", f"{draw_down.max.drawdown:.2f}"),
        ("% времени с открытыми позициями", f"{trades_analysis['len']['total'] / len(strategy) * 100:.2f}"),
        ("Количество прибыльных сделок", f"{trades_analysis.won.total}"),
        ("Количество убыточных сделок", f"{trades_analysis.lost.total}"),
        ("Соотношение количества прибыльных/убыточных сделок", f"{trades_analysis.won.total / trades_analysis.lost.total:.2f}"),
        ("Средний профит на сделку в %", f"{custom_analyzer['avg_won_per_trade']:.2f}"),
        ("Средний убыток на сделку в %", f"{custom_analyzer['avg_loss_per_trade']:.2f}"),
        ("Соотношение прибыль/убыток", f"{custom_analyzer['profit_loss_ratio']:.2f}"),
        ("Средняя длительность прибыльных сделок в барах", f"{trades_analysis.len.won.average:.2f}"),
        ("Средняя длительность убыточных сделок в барах", f"{trades_analysis.len.lost.average:.2f}"),
        ("Макс. прибыльных сделок подряд", f"{trades_analysis.streak.won.longest}"),
        ("Макс. убыточных сделок подряд", f"{trades_analysis.streak.lost.longest}")
    ]

    print("-" * 50)
    for description, value in parameters:
        print(f"{description}: {value}")
    print("-" * 50)

    if copy_to_clipboard:
        clipboard_data = [value for _, value in parameters]
        pyperclip.copy("\t".join(clipboard_data))

    if plot:
        cerebro.plot(style='candle', separate_plots=False, volume=False)

    if save_plots:
        save_strategy_plots(cerebro, strategy_class, ticker, interval)

    return strategy, parameters



def run_on_multiple_tickers(strategy_class, tickers, interval, start_date, end_date,
                 initial_cash=10_000, commission=0.0, plot=True, copy_to_clipboard=False,
                 save_plots=False, log_orders=False, **params):
    """
    Запускает тестирование стратегии на нескольких тикерах
    :param strategy_class: класс стратегии
    :param tickers: список тикеров ['AAPL', 'MSFT', 'GOOGL', 'AMZN'...]
    :param interval: интервал
    :param start_date: дата начала тестирования
    :param end_date: дата конца тестирования
    :param initial_cash: начальный капитал
    :param commission: комиссия
    :param plot: нужно ли выводить графики
    :param copy_to_clipboard: нужно ли копировать результаты тестирования в буфер обмена
    :param save_plots: нужно ли сохранять графики в папку стратегии
    :param log_orders: нужно ли логировать ордера
    :param params: параметры стратегии - например fast_sma_period=5, slow_sma_period=10
    :return: список объектов Strategy и список параметров
    """

    joint_parameters = []
    for ticker in tickers:
        strategy, parameters = simple_run(strategy_class=strategy_class,
                                        ticker=ticker,
                                        interval=interval,
                                        start_date=start_date,
                                        end_date=end_date,
                                        initial_cash=initial_cash,
                                        commission=commission,
                                        plot=plot,
                                        copy_to_clipboard=False,
                                        save_plots=save_plots,
                                        log_orders=log_orders,
                                        **params)
        joint_parameters.append(parameters)

    if copy_to_clipboard:
        strategies_clipboard = []
        for parameters in joint_parameters:
            strategy_params = "\t".join(str(value) for _, value in parameters)
            strategies_clipboard.append(strategy_params)

        final_clipboard_data = "\n".join(strategies_clipboard)
        pyperclip.copy(final_clipboard_data)