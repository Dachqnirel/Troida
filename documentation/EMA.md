# Определение EMA
**Экспоненциальные скользящие средние** (EMA – Exponential Moving Average) — это такое скользящее среднее, которое придаёт больший вес более свежим данным. 

# Формула расчета EMA

$$EMA_{t}(P)= \alpha\cdot P_{t}+(1-\alpha)\cdot EMA_{t-1}(P)$$
- $\alpha=\frac{2}{N+1}$ — коэффициент сглаживания, где $N$ —количество периодов,
- $P_{t}$ — текущая цена на момент $t$,
- $EMA_{t-1}$ — предыдущее значение экспоненциальной скользящей средней

# Как использовать
- Определения направления тренда
	- если цена находится выше линии $EMA$, это может значить о восходящем, если ниже — о нисходящем тренде.
- Генерации торговых сигналов
	- пересечение короткой линии $EMA$ (например с периодом 10) с длиной $EMA$(например с периодом 50) может сигнализировать о смене тренда
- Определения уровней поддержки и сопротивления

# Истоники
- [скользящая средняя в википедии](https://ru.wikipedia.org/wiki/%D0%A1%D0%BA%D0%BE%D0%BB%D1%8C%D0%B7%D1%8F%D1%89%D0%B0%D1%8F_%D1%81%D1%80%D0%B5%D0%B4%D0%BD%D1%8F%D1%8F)
- [Статья с TABTRADER](https://tabtrader.com/ru/academy/articles/exponential-moving-average-ema-explained?utm_source=chatgpt.com)
- [статья с сайта capital.com](https://capital.com/ru-int/learn/technical-analysis/exponential-moving-average?utm_source=chatgpt.com)
- [статья с Binance Academy](https://academy.binance.com/ru/glossary/exponential-moving-average-ema?utm_source=chatgpt.com)
- [статья с BitDegree](https://ru.bitdegree.org/crypto/obuchenie/kripto-terminy/chto-takoe-eksponencialnaya-skolzyashaya-srednyaya?utm_source=chatgpt.com)
