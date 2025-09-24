import backtrader as bt
import numpy as np

class SortinoRatioAnalyzer(bt.Analyzer):
    def __init__(self):
        self.returns = []

    def next(self):
        daily_return = self.strategy.broker.get_value() / self.strategy.broker.get_cash() - 1
        self.returns.append(daily_return)

    def get_analysis(self):
        riskfreerate = 0  # безрисковая ставку считаем за 0
        returns = np.array(self.returns)
        downside_returns = np.where(returns < riskfreerate, returns - riskfreerate, 0)
        downside_std = np.std(downside_returns[downside_returns < 0])

        avg_return = np.mean(returns)
        if downside_std == 0:
            return {'Sortino Ratio': float('inf'), 'Reason': 'волатильность вниз равна нулю'}

        sortino = (avg_return - riskfreerate) / downside_std
        return {'Sortino Ratio': sortino}