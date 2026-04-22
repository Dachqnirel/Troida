# Фьючерсный бэктест на Backtrader

В этой директории находится отдельный модуль для прогона фьючерсной стратегии на `backtrader` по данным из CSV/Parquet.

## Как фьючерсы моделируются в Backtrader

`backtrader` переводит инструмент в режим `futures-like`, если у брокера задана схема комиссии с `margin`:

- `commission` становится фиксированной комиссией за контракт
- `margin` становится гарантийным обеспечением на 1 контракт
- `multiplier` (`mult`) участвует в расчёте PnL по контракту

Именно поэтому в раннере используется:

```python
cerebro.broker.setcommission(
    commission=15.0,
    margin=15000.0,
    mult=10.0,
)
```

## Логика стратегии

Стратегия `FuturesParabolicSARStrategy` использует:

- `Parabolic SAR` как основной сигнал на вход/разворот
- `EMA` как фильтр направления тренда
- long и short, что типично для фьючерсной торговли

Правила:

- если `close > PSAR` и `close > EMA` -> открывается или удерживается `long`
- если `close < PSAR` и `close < EMA` -> открывается или удерживается `short`
- если сигнал нейтральный -> позиция закрывается

## Запуск

1. Создать окружение на `Python 3.12`
2. Установить зависимости:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r ./createBacktests/requirements.txt
```

3. Запустить бэктест:

```bash
python ./createBacktests/runFuturesBacktest.py \
  -f ./createBacktests/configureFuturesBacktest.yml
```

Для сохранения JSON-сводки:

```bash
python ./createBacktests/runFuturesBacktest.py \
  -f ./createBacktests/configureFuturesBacktest.yml \
  -o ./createBacktests/output/summary.json
```
