import backtrader as bt


class CustomAnalyzer(bt.Analyzer):
    def __init__(self):
        self.total_won_profits = []  # список значений прибыли в процентах
        self.total_lost_profits = [] # список значений убытков в процентах
        self.current_open_value = 0  # текущая стоимость позиции
        self.current_realized_pnl = 0  # заработанная прибыль в деньгах
        self.current_size = 0  # текущий размер позиции

    def notify_trade(self, trade):
        # Сделка открылась
        if trade.isopen:
            self.current_size = abs(trade.size)
            self.current_open_value = self.current_size * trade.price
            self.current_realized_pnl = 0

        # Сделка закрылась
        elif trade.isclosed:
            self.current_realized_pnl = trade.pnl

            # делаем проверку, что сделка была открыта
            if self.current_open_value > 0:
                profit_percent = (self.current_realized_pnl / self.current_open_value) * 100

                if profit_percent > 0:
                    self.total_won_profits.append(profit_percent)

                elif profit_percent < 0:
                    self.total_lost_profits.append(abs(profit_percent))

            # Обнуляем значения после закрытия сделки
            self.current_open_value = 0
            self.current_realized_pnl = 0
            self.current_size = 0

    def get_analysis(self):
        avg_won_per_trade = (sum(self.total_won_profits) / len(self.total_won_profits) if self.total_won_profits else 0)
        avg_loss_per_trade = (sum(self.total_lost_profits) / len(self.total_lost_profits) if self.total_lost_profits else 0)
        profit_loss_ratio = avg_won_per_trade / avg_loss_per_trade if avg_loss_per_trade != 0 else float('inf')
        buy_and_hold_profit = ((self.data.close[0] - self.data.close[-len(self.data) + 1]) / self.data.close[-len(self.data) + 1]) * 100
        return {
            'avg_won_per_trade': avg_won_per_trade,
            'avg_loss_per_trade': avg_loss_per_trade,
            'profit_loss_ratio': profit_loss_ratio,
            'buy_and_hold_profit': buy_and_hold_profit
        }