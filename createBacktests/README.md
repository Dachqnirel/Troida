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

## Логика стратегии ADX

Стратегия `FuturesADXStrategy` использует:

- `ADX` как фильтр силы тренда
- `+DI` и `-DI` как сигнал направления тренда
- `EMA` как фильтр направления тренда
- `ATR` для защитного стопа
- long и short, что типично для фьючерсной торговли

Правила:

- если `ADX >= adx_entry_level`, `+DI > -DI` и `close > EMA` -> открывается или удерживается `long`
- если `ADX >= adx_entry_level`, `-DI > +DI` и `close < EMA` -> открывается или удерживается `short`
- если ADX падает ниже `adx_exit_level` -> позиция закрывается
- если цена проходит против позиции больше чем `ATR * atr_stop_multiplier` от цены входа -> позиция закрывается

В YAML-конфигурации стратегия выбирается параметром `strategy.name`:

- `adx` запускает `FuturesADXStrategy`
- `psar` запускает прежнюю `FuturesParabolicSARStrategy`

Старые конфиги с `psar_period`, `psar_af` или `psar_afmax` без `strategy.name` также будут распознаны как PSAR-конфиги.

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
