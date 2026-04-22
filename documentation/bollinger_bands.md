
# **Bollinger Bands** — стратегия на основе полос Боллинджера

## Что это такое

**Bollinger Bands** — индикатор, который показывает текущую **волатильность**.  
Состоит из **скользящей средней** и двух границ: верхней и нижней, отстоящих от неё на **несколько стандартных отклонений**.

Идея: если цена резко выходит за границы, это может означать начало тренда или его завершение.

---

## Как работает стратегия

Условия:

1. **Покупка**, если цена закрытия **выше верхней границы**  
2. **Продажа**, если цена закрытия **ниже нижней границы**  
3. **Размер позиции** — 5% от текущего капитала  
4. Стратегия допускает **несколько покупок** подряд

Пример кода:
```python
if self.data.close[0] > self.bb.lines.top[0]:
    self.buy(size=self.calculate_trade_size())

elif self.data.close[0] < self.bb.lines.bot[0]:
    if self.position.size > 0:
        self.close()
```

Расчёт позиции:
```python
size = (cash * 0.05) / self.data.close[0]
```

---

## Как использовать

Пример запуска:
```python
strategy = simple_run(
    strategy_class=BollingerBreakout,
    ticker='AAPL',
    interval='1d',
    start_date="01.01.21",
    end_date="01.06.24",
    log_orders=False
)
```

---

## Особенности

**Плюсы:**
- Простая логика
- Автоматический контроль риска
- Работает на любом таймфрейме

**Минусы:**
- Много ложных сигналов в боковике
- Не учитывает объёмы
- Лучше работает с фильтрацией по тренду

---

## Полезные ссылки

1. [Документация Backtrader — Bollinger Bands](https://www.backtrader.com/docu/indicators-reference/#bollingerbands)
2. [Официальный сайт BollingerBands](https://www.bollingerbands.com/)
3. [Видеоуроки по стратегии на Python](https://www.youtube.com/results?search_query=bollinger+bands+strategy+python)
