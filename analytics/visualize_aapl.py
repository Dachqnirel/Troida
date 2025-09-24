import matplotlib.pyplot as plt
from backtesting.historical_data_access import get_ticker_dataframe

# Получаем данные для AAPL
df = get_ticker_dataframe(
    ticker='AAPL',
    interval='1d',
    start_date='01.01.21',
    end_date='01.03.25'
)

if df is not None:
    # Создаем график
    plt.figure(figsize=(12, 6))
    plt.plot(df.index, df['close'], label='Цена закрытия')
    
    # Настраиваем внешний вид графика
    plt.title('История цен акций AAPL', fontsize=14)
    plt.xlabel('Дата', fontsize=12)
    plt.ylabel('Цена (USD)', fontsize=12)
    plt.grid(True)
    plt.legend()
    
    # Поворачиваем метки дат для лучшей читаемости
    plt.xticks(rotation=45)
    
    # Автоматически настраиваем отступы
    plt.tight_layout()
    
    # Показываем график
    plt.show()
else:
    print("Не удалось получить данные для AAPL") 