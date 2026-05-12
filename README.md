# Bybit Parser

Парсер свечей с биржи Bybit. Поддерживает два режима работы: **HTTP-сервер** (GET-запросы, JSON-ответы) и **CLI** (экспорт в CSV).

---

## Установка

```bash
pip install -r requirements.txt
```

**Зависимости:** `pybit`, `python-dotenv`, `fastapi`, `uvicorn`

---

## Режим HTTP-сервера

### Запуск

```bash
# Локально (127.0.0.1:8000)
python byparser.py --serve

# Свой адрес и порт
python byparser.py --serve --host 0.0.0.0 --port 9000
```

Интерактивная документация (Swagger UI) доступна по адресу:
```
http://127.0.0.1:8000/docs
```

---

### GET /candles

Возвращает свечи в формате JSON.

#### Параметры запроса

| Параметр   | Тип    | Обязательный | По умолчанию | Описание |
|------------|--------|:------------:|:------------:|----------|
| `symbol`   | string | ✅           | —            | Торговая пара: `BTCUSDT`, `ETHUSDT` и т.д. |
| `interval` | string | ✅           | —            | Таймфрейм (см. таблицу ниже) |
| `category` | string | ❌           | `spot`       | Тип рынка: `spot`, `linear`, `inverse` |
| `limit`    | int    | ❌           | `200`        | Количество свечей без диапазона (1–200). Игнорируется при `start`/`end` |
| `start`    | string | ❌           | —            | Начало диапазона: `YYYY-MM-DD` или `YYYY-MM-DD HH:MM:SS` (UTC) |
| `end`      | string | ❌           | —            | Конец диапазона: `YYYY-MM-DD` или `YYYY-MM-DD HH:MM:SS` (UTC) |

> При указании `start` и/или `end` выполняется автоматическая пагинация — возвращаются все свечи за период (без ограничения в 200).

#### Допустимые значения interval

| Значение | Период свечи   |
|----------|---------------|
| `1`      | 1 минута      |
| `3`      | 3 минуты      |
| `5`      | 5 минут       |
| `15`     | 15 минут      |
| `30`     | 30 минут      |
| `60`     | 1 час         |
| `120`    | 2 часа        |
| `240`    | 4 часа        |
| `360`    | 6 часов       |
| `720`    | 12 часов      |
| `D`      | 1 день        |
| `W`      | 1 неделя      |
| `M`      | 1 месяц       |

#### Формат ответа

```json
{
  "count": 100,
  "candles": [
    {
      "timestamp": 1704067200000,
      "datetime":  "2024-01-01 00:00:00",
      "open":      42000.0,
      "high":      42500.0,
      "low":       41800.0,
      "close":     42300.0,
      "volume":    1234.56,
      "turnover":  52000000.0
    }
  ]
}
```

Свечи отсортированы в хронологическом порядке (от старых к новым).

#### Примеры запросов

**Последние 100 часовых свечей BTCUSDT (спот):**
```
GET /candles?symbol=BTCUSDT&interval=60&category=spot&limit=100
```

**15-минутные свечи ETHUSDT (фьючерс) за март 2024:**
```
GET /candles?symbol=ETHUSDT&interval=15&category=linear&start=2024-03-01&end=2024-04-01
```

**Дневные свечи SOLUSDT за конкретный день:**
```
GET /candles?symbol=SOLUSDT&interval=D&category=spot&start=2024-01-01&end=2024-01-02
```

**5-минутные свечи с точным временем:**
```
GET /candles?symbol=BTCUSDT&interval=5&category=linear&start=2024-03-01 10:00:00&end=2024-03-01 12:00:00
```

#### Примеры через curl и Python

```bash
curl "http://127.0.0.1:8000/candles?symbol=BTCUSDT&interval=60&category=spot&limit=50"
```

```python
import requests

r = requests.get("http://127.0.0.1:8000/candles", params={
    "symbol":   "BTCUSDT",
    "interval": "60",
    "category": "spot",
    "limit":    50,
})
data = r.json()
print(data["count"])       # количество свечей
print(data["candles"][0])  # первая свеча
```

#### Коды ошибок

| Код | Причина |
|-----|---------|
| `400` | Неверный параметр (`interval`, `category`, формат даты) |
| `404` | Свечи не получены (неверная пара, нет данных за период) |

---

## Режим CLI

Загружает свечи и сохраняет в CSV-файл.

### Использование

```bash
python byparser.py -s ПАРА -c КАТЕГОРИЯ -i ИНТЕРВАЛ [опции]
```

### Параметры

| Параметр               | Описание |
|------------------------|----------|
| `-s`, `--symbol`       | Торговая пара (обязательный) |
| `-c`, `--category`     | Тип рынка: `spot`, `linear`, `inverse` (обязательный) |
| `-i`, `--interval`     | Таймфрейм (обязательный): `1`, `3`, `5`, `15`, `30`, `60`, `120`, `240`, `360`, `720`, `D`, `W`, `M` |
| `-l`, `--limit`        | Количество свечей без диапазона (1–200, по умолчанию 200) |
| `--start`              | Начало диапазона: `YYYY-MM-DD` или `YYYY-MM-DD HH:MM:SS` |
| `--end`                | Конец диапазона: `YYYY-MM-DD` или `YYYY-MM-DD HH:MM:SS` |
| `-o`, `--output`       | Путь к CSV-файлу (по умолчанию: `<ПАРА>_<КАТЕГОРИЯ>_<ИНТЕРВАЛ>.csv`) |

### Примеры

```bash
# Последние 200 часовых свечей BTCUSDT
python byparser.py -s BTCUSDT -c spot -i 60 -l 200 -o btc.csv

# Все 15-минутные свечи ETHUSDT за январь 2024
python byparser.py -s ETHUSDT -c linear -i 15 --start 2024-01-01 --end 2024-02-01 -o eth.csv

# Дневные свечи SOLUSDT за 2023 год
python byparser.py -s SOLUSDT -c spot -i D --start 2023-01-01 --end 2024-01-01 -o sol_2023.csv
```

### Формат CSV

```
timestamp,datetime,open,high,low,close,volume,turnover
1704067200000,2024-01-01 00:00:00,42000.0,42500.0,41800.0,42300.0,1234.56,52000000.0
```

---

## Очистка аномалий

Перед сохранением/возвратом свечи автоматически проверяются и очищаются:

| Тип аномалии | Действие |
|---|---|
| Дубли по timestamp | Удаляются |
| Нарушение OHLC-логики (`high < low` и т.д.) | Исправляются или удаляются |
| Нулевой / отрицательный объём | Удаляются |
| Ценовые выбросы (Z-score > 3.0) | Удаляются |
| Пропуски в хронологии | Логируются |

---

## Конфигурация (.env)


Создайте файл `.env` в директории скрипта для настройки логирования:

```env
LOG_PATH=logs                  # директория лог-файлов
LOG_FILE_SIZE=5242880          # максимальный размер файла в байтах (5 МБ)
BACKUP_FILES_COUNT=5           # количество резервных копий лога
```

Логи пишутся в `logs/byparser.log`.

---

## Развёртывание на веб-сервере

### Требования

- Python 3.10+
- Linux-сервер (Ubuntu 22.04 / Debian 12 и т.д.)
- Открытый порт (например, `8000`) или обратный прокси (nginx)

---

### 1. Клонирование и установка зависимостей

```bash
git clone <репозиторий> /opt/byparser
cd /opt/byparser
pip install -r requirements.txt
```

---

### 2. Настройка окружения

```bash
cp .env.example .env   # или создайте .env вручную
nano .env
```

```env
LOG_PATH=logs
LOG_FILE_SIZE=5242880
BACKUP_FILES_COUNT=5
```

---

### 3. Запуск через systemd 

Создайте unit-файл:

```bash
sudo nano /etc/systemd/system/byparser.service
```

```ini
[Unit]
Description=Bybit Parser HTTP Server
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/byparser/bybit_parser
ExecStart=/usr/bin/python3 byparser.py --serve --host 0.0.0.0 --port 80
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

## Поддерживаемые торговые пары

Скрипт поддерживает любую пару, доступную на Bybit. Ниже приведены наиболее популярные.

### Спот (--category spot)

| Пара | Описание |
|---|---|
| `BTCUSDT` | Bitcoin / Tether |
| `ETHUSDT` | Ethereum / Tether |
| `SOLUSDT` | Solana / Tether |
| `BNBUSDT` | BNB / Tether |
| `XRPUSDT` | XRP / Tether |
| `DOGEUSDT` | Dogecoin / Tether |
| `ADAUSDT` | Cardano / Tether |
| `AVAXUSDT` | Avalanche / Tether |
| `DOTUSDT` | Polkadot / Tether |
| `MATICUSDT` | Polygon / Tether |
| `LTCUSDT` | Litecoin / Tether |
| `LINKUSDT` | Chainlink / Tether |
| `UNIUSDT` | Uniswap / Tether |
| `ATOMUSDT` | Cosmos / Tether |
| `NEARUSDT` | NEAR Protocol / Tether |

> Полный список пар доступен на [bybit.com](https://www.bybit.com). Название пары передаётся в аргумент `-s` в верхнем регистре.
