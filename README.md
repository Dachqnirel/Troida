# Moscow Polytech University
![some text](https://sun9-44.userapi.com/s/v1/if2/-56bVS1t1sjIx3cO_p5eevk2150OLx5k8yZbU8tn5t8ppiQKF-1Kex6QJK1bVosHkDyHNjng75aNoaoT6QK94wT8.jpg?quality=95&as=32x7,48x11,72x17,108x25,160x38,240x56,360x84,480x113,540x127,640x150,720x169,1080x253,1280x300,1440x338,2003x470&from=bu&cs=2003x0)
## Подкоманда "Данные и бэктест"

### Состав команды:
1. [Макарова Софья 241-363](https://gitverse.ru/sonteikamaki)
2. [Крупенин Владимир 231-3210](https://gitverse.ru/bamsz)
3. [Ортанов Астемир 241-331](https://gitverse.ru/ctotochtoto)
4. [Саливонов Никита 221-361](https://gitverse.ru/yoshiultras)
5. [Леоненко Роман 241-3211](https://gitverse.ru/k0swel)
6. [Молодкин Тимофей 241-363](https://gitverse.ru/timofeyagiwait)

### Задачи:
[\*клик\*](https://docs.google.com/spreadsheets/d/1-eBKuSCimcO7rF1RXgTLscJefoh6DgPYIRA3L1fgVOA/edit?gid=0#gid=0)


## Скрипт createReports.py
### Основное назначение
Скрипт **createReports.py** служит для построения отчётов по акциям и соответствующим параметрам (пример файла конфигурации задан в директории **createReports/configureScript.yml**) или в источнике ниже.
```yaml
instrumentTypes:
  INSTRUMENT_TYPE_UNSPECIFIED: &unspecified 0
  INSTRUMENT_TYPE_BOND: &bond 1
  INSTRUMENT_TYPE_SHARE: &share 2
  INSTRUMENT_TYPE_CURRENCY: &currency 3
  INSTRUMENT_TYPE_ETF: &etf 4
  INSTRUMENT_TYPE_FUTURES: &futures 5
  INSTRUMENT_TYPE_SP: &sp 6
  INSTRUMENT_TYPE_OPTION: &option 7
  INSTRUMENT_TYPE_CLEARING_CERTIFICATE: &certificate 8
  INSTRUMENT_TYPE_INDEX: &index 9
  INSTRUMENT_TYPE_COMMODITY: &commodity 10

fromDate: &from_date "21.10.2024 00:00:00"
toDate: &to_date "21.10.2025 00:00:00"

stock:
  Sberbank:
    ticker: "SBER"
    interval: 2H
    from_date: *from_date
    to_date: *to_date
    instrument_type: *share

  T-Technology:
    ticker: "T"
    interval: 2H
    from_date: *from_date
    to_date: *to_date
    instrument_type: *share

  VTB:
    ticker: "VTBR"
    interval: 2H
    from_date: *from_date
    to_date: *to_date
    instrument_type: *share

  Yandex:
    ticker: "YDEX"
    interval: 2H
    from_date: *from_date
    to_date: *to_date
    instrument_type: *share

  X5:
    ticker: "X5"
    interval: 2H
    from_date: *from_date
    to_date: *to_date
    instrument_type: *share

  VK:
    ticker: "VKCO"
    interval: 2H
    from_date: *from_date
    to_date: *to_date
    instrument_type: *share

  Lukoil:
    ticker: "LKOH"
    interval: 2H
    from_date: *from_date
    to_date: *to_date
    instrument_type: *share

  PIK:
    ticker: "PIKK"
    interval: 2H
    from_date: *from_date
    to_date: *to_date
    instrument_type: *share

  Norilsk Nikel:
    ticker: "GMKN"
    interval: 2H
    from_date: *from_date
    to_date: *to_date
    instrument_type: *share

  SeverStal:
    ticker: "CHMF"
    interval: 2H
    from_date: *from_date
    to_date: *to_date
    instrument_type: *share
```
## Активация
В файл ```.env``` поместить токен Т-Инвестиций.
Создать виртуальное окружение, используя ```python -m vemv ./.env```, затем перейти в него ```./.env/Scripts/activate```
Установить зависимости ```pip install -r requirements.txt```

Запустить скрипт при помощи вызова команды ```python .createReports.py -f <путь к .yaml конфигурации> -d <путь к директории, куда необходимо загрузить отчёты>```

Для справки может служить команда ```python ./createReports.py --help```
