import backtrader as bt
from backtesting.historical_data_access import get_ticker_dataframe
from backtesting.custom_analyzers import KellyCriterionAnalyzer, SortinoRatioAnalyzer, CustomAnalyzer
from backtesting.logger_config import setup_logger


logger = setup_logger()

'''
TODO:
walk forward optimization:
1) настройка величины in-sample и out-of-sample данных
2) вывод средних результатов для in-sample и out-of-sample данных
3) вывод графика, где снизу наши периоды и сверху equity curve

и на этом же графики вывести другую кривую - наша equti curve, если бы мы не изменяли параметры каждый раз.
то есть сравнение между "оптимизируем с 2016-2020 и смотрим на результат в 2021-2025" и "оптимизируем walkforward с 2016"
    
ДОСТУПНЫЕ БИБЛИОТКЕИ:
https://github.com/jodhangill/GenTrader - подбор параметров эволюционно (консольное приложение) 
https://github.com/happydasch/btplotting - более гибкий вывод графиков
https://github.com/harveybc/heuristic-strategy - генетический отбор стратегий (консольное приложение) 
'''


def simple_optimization(strategy_class,
                        ticker,
                        interval,
                        in_sample_start_date,
                        in_sample_end_date,
                        initial_cash=10_000,
                        commission=0.0,
                        log_orders=False,
                        **params_ranges):
    """
    Функция для простой оптимизации стратегии (1 период in-sample)
    Возвращает список объектов класса Strategy, которые были получены в результате оптимизации
    :param strategy_class: класс стратегии
    :param ticker: тикер
    :param interval: интервал
    :param in_sample_start_date: дата начала in-sample оптимизации
    :param in_sample_end_date: дата конца in-sample оптимизации
    :param initial_cash: начальный капитал
    :param commission: комиссия
    :param log_orders: нужно ли логировать ордера
    :param params_ranges: диапазоны параметров для оптимизации - например fast_sma_period=range(1,5), slow_sma_period=range(5,10)
    :return: список объектов класса Strategy, которые были получены в результате оптимизации
    """

    logger.info("Запускаю оптимизацию параметров на IN-SAMPLE данных")
    in_sample_cerebro = bt.Cerebro()

    in_sample_cerebro.broker.setcash(initial_cash)
    in_sample_cerebro.broker.setcommission(commission=commission)

    in_sample_dataframe = get_ticker_dataframe(ticker, interval, in_sample_start_date, in_sample_end_date)
    in_sample_dataframe = bt.feeds.PandasData(dataname=in_sample_dataframe)
    in_sample_cerebro.adddata(in_sample_dataframe)

    in_sample_cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='TradeAnalyzer')
    in_sample_cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='SharpeRatio', annualize=True)
    in_sample_cerebro.addanalyzer(bt.analyzers.Returns, _name='Returns')
    in_sample_cerebro.addanalyzer(bt.analyzers.DrawDown, _name='DrawDown')
    in_sample_cerebro.addanalyzer(KellyCriterionAnalyzer, _name='Kelly')
    in_sample_cerebro.addanalyzer(SortinoRatioAnalyzer, _name="Sortino")
    in_sample_cerebro.addanalyzer(CustomAnalyzer, _name="CustomAnalyzer")
    in_sample_cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='TimeReturn')

    in_sample_cerebro.optstrategy(
        strategy_class,
        log_orders=log_orders,
        **params_ranges,

    )

    # optreturn=False нужен, чтобы мы получали список объектов класса Strategy (но это будет съедать много ресурсов!)
    # при optreturn=True мы получим только params (то есть параметры стратегии) и analyzers (то есть анализаторы, которые были в стратегии)
    optimization_results = in_sample_cerebro.run(optreturn=True)

    return optimization_results