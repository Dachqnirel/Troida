# Стратегия Vortex + Donchian + RSI + ATR

Трендово‑пробойная стратегия для OHLCV (в т.ч. крипта), с фильтрами по силе движения и режиму рынка.

**Файлы в папке:**

- `Vortex_Donchian_RSI.py` — логика стратегии, CLI, метрики
- `vortex_donchian_indicators.py` — расчёт индикаторов и режима `trend/bear`
- `csv_metrics.py` — загрузка CSV и `sharpe_and_sum` (используется, если в корне проекта нет `rolling_catboost.py`)

Если в корне репозитория есть `rolling_catboost.py`, скрипт возьмёт `load_csv` / `sharpe_and_sum` оттуда.

## Используемые индикаторы

| Индикатор | Назначение в стратегии | Справка в репозитории |
|-----------|------------------------|------------------------|
| **Vortex Indicator** (VI+, VI−) | Направление тренда: long при VI+ > VI−, short при VI− > VI+ | `documentation/Vortex_Indicator.md` |
| **Каналы Дончиана** (Upper, Lower, Mid) | Пробой верхней границы для long, нижней для short; Mid — ориентир выхода | `documentation/DonchianChannel.md` |
| **RSI** | Фильтр «перекупленности» для long (порог rsi_long) и «перепроданности» для short (rsi_short) | `documentation/RSI.md` |
| **EMA** | Фильтр тренда (цена выше/ниже EMA), в static‑режиме — наклон EMA для bull/bear при шортах; в adaptive — EMA(250) для торговли и режима | `documentation/EMA.md` |
| **ATR** | Фильтр волатильности: торгуем только когда ATR выше своего среднего за 100 баров | `documentation/ADX_ATR_indicators.md` (блок ATR) |

Дополнительно в **режиме `adaptive`** используется **оценка режима рынка** (`trend` / `bear`): сглаженный наклон EMA(250) по прошлым данным без заглядывания в будущее (см. `compute_regime` в `vortex_donchian_indicators.py`).

## Режимы запуска

### `static` (по умолчанию)

Один набор параметров Donchian/EMA/RSI на весь ряд. Опционально шорты с режимом `short_mode`: `always` | `bear` | `never` и фильтром по наклону EMA.

### `adaptive` (рекомендуется для «как в реале»)

На каждом баре по **прошлой** истории определяется `trend` или `bear`:

- в **trend**: long только при пробое Donchian с периодом **40**, без short;
- в **bear**: short при пробое нижней границы Donchian с периодом **55** (и фильтрах VI/RSI/ATR); long в этом режиме **не открывается** (только удержание/выход уже открытого long при переключении режима обрабатывается правилами выхода).

Пороги по умолчанию в adaptive: `rsi_long` 60 (long), `rsi_short` 35 (short), EMA для сигналов — 250.

## Правила входа и выхода (сводно)

**Long (типичный набор условий):**

- VI+ > VI−
- Close > EMA
- Пробой Upper Donchian: Close пересекает Upper снизу вверх (сравнение с Upper на предыдущем баре)
- RSI ≥ rsi_long
- ATR > среднее ATR за 100 баров
- В static при включённом bull‑фильтре: наклон EMA не ниже порога

**Выход из long:**

- VI+ < VI− **или** Close < EMA **или** Close < Mid Donchian

**Short** (если разрешён режимом):

- VI− > VI+
- Close < EMA
- Пробой Lower Donchian (аналогично через предыдущий бар)
- RSI ≤ rsi_short
- ATR‑фильтр

**Выход из short:** симметрично (разворот VI, возврат выше EMA или выше Mid).

Комиссия моделируется как **б.п. на смену позиции** (`--cost_bps`, по умолчанию 5).

## Запуск из корня проекта

```bash
python strategies/VortexDonchianRSI/Vortex_Donchian_RSI.py --csv data/BTCUSDT_2h.csv --mode adaptive
```

Пресеты для ручного сравнения:

```bash
python strategies/VortexDonchianRSI/Vortex_Donchian_RSI.py --csv data/BTCUSDT_2h.csv --preset trend --mode static --allow_short 0
python strategies/VortexDonchianRSI/Vortex_Donchian_RSI.py --csv data/BTCUSDT_2h.csv --preset bear --mode static
```

## Метрики в выводе

- **Final equity** — множитель капитала (1.15 ≈ +15%).
- **CAGR**, **Max Drawdown**, **Profit Factor**, **Sharpe**, **Sum** — см. общие заметки по бэктесту в `documentation/`.


