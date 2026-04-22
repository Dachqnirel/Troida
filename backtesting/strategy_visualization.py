import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import os
from backtrader import Cerebro
import inspect
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.dates import DateFormatter
import backtrader as bt


def save_strategy_plots(cerebro: Cerebro, strategy_class, ticker: str, interval: str, output_dir: str = 'strategies'):
    """
    Сохраняет графики стратегии в папку стратегии
    """
    import matplotlib
    original_backend = matplotlib.get_backend()  # Сохраняем текущий бэкенд

    try:
        # Получаем путь к файлу стратегии
        strategy_file = inspect.getfile(strategy_class)
        strategy_dir = os.path.dirname(strategy_file)

        # Создаем имя файла для графика
        filename = f"{ticker}_{interval}_plot.png"
        filepath = os.path.join(strategy_dir, filename)

        # Сохраняем график
        matplotlib.use('Agg')  # Без GUI
        figs = cerebro.plot(style='candle', separate_plots=False, volume=False, quiet=True)
        if figs:
            fig = figs[0][0]
            fig.set_size_inches(16, 9)
            fig.savefig(filepath, dpi=100, bbox_inches='tight')
            plt.close(fig)
            print(f"График сохранен: {filepath}")

    except Exception as e:
        print(f"Ошибка при сохранении графика: {str(e)}")

    finally:
        # Не пытаемся вернуть бэкенд, чтобы избежать ошибок с Qt
        pass

def compare_equity_curves(strategies_list):
    """
    Сравнение equity curve нескольких стратегий. Выводит график
    :param strategies_list: список в формате [(strategy_class1, label1), (strategy_class2, label2), ...]
    """
    equity_curves = []
    labels = []
    for strategy_class, label in strategies_list:
        print(f"Запуск стратегии: {label}")
        equity_curves.append(strategy_class.equity_curve)
        labels.append(label)

    plt.figure()
    for eq, lab in zip(equity_curves, labels):
        plt.plot(eq, label=lab)
    plt.title('Сравнение Equity Curve стратегий')
    plt.xlabel('Шаг (бар)')
    plt.ylabel('Стоимость портфеля')
    plt.legend()
    plt.grid(True)
    plt.xticks(rotation=45)
    plt.show()


# Функция визуализации капитала и просадки
def visualize_performance(strategy, title='Анализ стратегии'):
    portfolio = strategy.portfolio_values
    dates = strategy.dates
    
    # Расчет просадки
    peak = -np.inf
    drawdown = []
    for val in portfolio:
        if val > peak:
            peak = val
        dd = (peak - val) / peak * 100
        drawdown.append(dd)

    plt.style.use('ggplot')
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    fig.suptitle(title, fontsize=14, fontweight='bold')

    # Капитал
    ax1.plot(dates, portfolio, color='limegreen', label='Капитал')
    ax1.set_ylabel('Капитал ($)')
    ax1.legend()
    ax1.grid(True)

    # Просадка
    ax2.fill_between(dates, drawdown, color='red', alpha=0.3)
    ax2.plot(dates, drawdown, color='darkred')
    ax2.set_ylabel('Просадка (%)')
    ax2.set_xlabel('Дата')
    ax2.legend(['Просадка'])
    ax2.grid(True)

    # Аннотация максимальной просадки
    max_dd = max(drawdown)
    max_idx = drawdown.index(max_dd)
    ax2.annotate(f'Max DD: {max_dd:.2f}%',
                 xy=(dates[max_idx], max_dd),
                 xytext=(10, 10),
                 textcoords='offset points',
                 arrowprops=dict(arrowstyle='->'))
    plt.show()


# Стилизованная функция отображения значения портфеля
def plot_portfolio_value(strategy):
    plt.style.use('dark_background')

    portfolio_values = strategy[0].portfolio_values
    timestamps = strategy[0].timestamps

    fig, ax = plt.subplots(figsize=(12, 5), facecolor='#0a0a0a')

    # График изменения капитала
    ax.plot(timestamps, portfolio_values, label='Капитал',
            color='#00FFAA', linewidth=1, alpha=0.9)

    # Подсветка области под кривой
    ax.fill_between(timestamps, portfolio_values, min(portfolio_values),
                    color='#00FFAA', alpha=0.1)

    # Стилизация
    ax.set_xlabel('Дата', fontsize=12, color='white', labelpad=10)
    ax.set_ylabel('Капитал (USDT)', fontsize=12, color='white', labelpad=10)
    ax.set_title('Динамика торгового капитала',
                 fontsize=14, color='white', pad=20, fontweight='bold')

    # Сетка и оси
    ax.grid(True, linestyle='--', linewidth=0.5, alpha=0.3, color='white')
    ax.spines['bottom'].set_color('#404040')
    ax.spines['left'].set_color('#404040')
    ax.tick_params(axis='x', colors='white')
    ax.tick_params(axis='y', colors='white')

    # Форматирование дат
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.xticks(rotation=45, fontsize=9)
    plt.yticks(fontsize=10)

    # Легенда
    legend = ax.legend(facecolor='#1a1a1a', edgecolor='none',
                       fontsize=10, loc='upper left')
    for text in legend.get_texts():
        text.set_color('white')

    plt.tight_layout()
    plt.show()

def compare_price_pnl(strategy, window_days=30):
    """
    Визуализирует результаты стратегии:
    - Ценовой график (вверху)
    - Средний PnL и вероятность прибыли (внизу) с скользящими средними
    """

    # --- Извлечение ценовых данных ---
    data = strategy.datas[0]
    price_dates = [bt.num2date(t) for t in data.datetime.array]
    price_df = pd.DataFrame({
        'datetime': pd.to_datetime(price_dates),
        'close': data.close.array
    }).set_index('datetime')

    # --- Проверка наличия данных о сделках ---
    if not hasattr(strategy, 'trades_data'):
        raise AttributeError("Стратегия не содержит данных о сделках.")

    trades_df = pd.DataFrame(strategy.trades_data)

    if trades_df.empty:
        print("Нет совершенных сделок.")
        return

    # --- Преобразование datetime из num2date ---
    # trades_df['datetime'] может быть числом (float) от backtrader
    trades_df['datetime'] = trades_df['datetime'].apply(
        lambda x: bt.num2date(x) if isinstance(x, (int, float)) else x
    )
    trades_df['datetime'] = pd.to_datetime(trades_df['datetime'])
    trades_df = trades_df.set_index('datetime')

    # --- Агрегация по дням ---
    daily_pnl = trades_df.resample('D').agg({'pnl': 'sum'}).fillna(0)
    daily_pnl['is_profit'] = (daily_pnl['pnl'] > 0).astype(int)

    # --- Расчёт скользящих метрик ---
    daily_pnl['avg_pnl'] = daily_pnl['pnl'].rolling(window=window_days).mean()
    daily_pnl['profit_prob'] = daily_pnl['is_profit'].rolling(window=window_days).mean()

    # --- Построение графиков ---
    fig, axes = plt.subplots(2, 1, figsize=(16, 9), gridspec_kw={'height_ratios': [2, 1]}, sharex=True)

    # График цены
    axes[0].plot(
        price_df.index,
        price_df['close'],
        color='navy',
        linewidth=1.5,
        label='Цена закрытия'
    )
    axes[0].set_title('Ценовые данные', fontsize=14)
    axes[0].set_ylabel('Цена ($)', fontsize=12)
    axes[0].grid(True)
    axes[0].legend(loc='upper left')

    # График метрик
    ax_pnl = axes[1]
    ax_prob = ax_pnl.twinx()

    ax_pnl.plot(
        daily_pnl.index,
        daily_pnl['avg_pnl'],
        color='blue',
        linestyle='-',
        linewidth=1.5,
        label=f'Средний PnL ({window_days} дней)'
    )

    ax_prob.plot(
        daily_pnl.index,
        daily_pnl['profit_prob'] * 100,
        color='orange',
        linestyle='--',
        linewidth=1.5,
        label=f'Вероятность прибыли ({window_days} дней)'
    )

    axes[1].set_title('Метрики эффективности стратегии', fontsize=14)
    ax_pnl.set_ylabel('Средний PnL ($)', fontsize=12)
    ax_prob.set_ylabel('Вероятность', fontsize=12)
    axes[1].grid(True)

    # Легенды
    lines1, labels1 = ax_pnl.get_legend_handles_labels()
    lines2, labels2 = ax_prob.get_legend_handles_labels()
    all_lines = lines1 + lines2
    all_labels = labels1 + labels2
    axes[1].legend(all_lines, all_labels, loc='upper left', fontsize=10)

    # Форматирование осей X
    date_format = DateFormatter("%b %Y")
    for ax in axes:
        ax.xaxis.set_major_formatter(date_format)
    fig.autofmt_xdate()

    plt.tight_layout()
    plt.show()