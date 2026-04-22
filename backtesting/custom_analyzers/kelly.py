import backtrader as bt

class KellyCriterionAnalyzer(bt.Analyzer):
    def __init__(self):
        self.trades = []

    def notify_trade(self, trade):
        if trade.isclosed:
            pnl = trade.pnl
            self.trades.append(pnl)

    def get_analysis(self):
        wins = [pnl for pnl in self.trades if pnl > 0]
        losses = [abs(pnl) for pnl in self.trades if pnl < 0]

        num_wins = len(wins)
        num_losses = len(losses)
        total = num_wins + num_losses

        if total == 0 or len(losses) == 0:
            return {'Kelly Criterion': None, 'Reason': 'Not enough data or no losses'}

        win_rate = num_wins / total
        avg_win = sum(wins) / num_wins if num_wins else 0
        avg_loss = sum(losses) / num_losses

        reward_risk_ratio = avg_win / avg_loss

        kelly = (reward_risk_ratio * win_rate  - (1 - win_rate)) / reward_risk_ratio

        return {
            'Kelly Criterion': round(kelly, 4),
        }