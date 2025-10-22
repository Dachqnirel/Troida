from dotenv import load_dotenv
from os import getenv
from packages.logging import logger
import packages.tAPI as tAPI
import yaml
from typing import Union, IO

tAPI.TINKOFF_TOKEN = getenv('TINKOFF_TOKEN') # в модуль tAPI помещаем токен Т-инвестиций.

    
def configureShoresToCollectFromCongigureFile(yaml_file: IO[str]) -> list[dict]:
    """Парсинг из .yaml файла конфигурации тинкера, from_date, to_date, interval, instrumentType

    Args:
        yaml_file (IO[str]): объект .yaml файла

    Returns:
        list[dict]: список словарей. Словарь имеет формат: {'ticker': 'some-data', 'from_date': 'some-data', 'to_date': 'some-data', 'interval': 'some-data', 'instrument_type': 'some-data'}
    """    
    rawConfig: dict = yaml.safe_load(yaml_file)
    shoresToCollect: list[dict] = list() # список, представляющий собой контейнер для входа в функцию tAPI.load_multiple_candles()
    for stockName in rawConfig['stock']:
        stockInfo: dict = rawConfig['stock'][stockName]
        stockInfo['from_date'] = tAPI.datetime.strptime(stockInfo['from_date'], '%d.%m.%Y').replace(tzinfo=tAPI.timezone.utc)
        stockInfo['to_date'] = tAPI.datetime.strptime(stockInfo['to_date'], '%d.%m.%Y').replace(tzinfo=tAPI.timezone.utc)
        shoresToCollect.append(stockInfo)
    return shoresToCollect


with open('./configureScript.yml', 'r', encoding='utf-8') as file:
    shoresDictionary: list[dict] = configureShoresToCollectFromCongigureFile(file)
    


def detect_anomalies(data: tAPI.pd.DataFrame) -> int:
    
    def detect_zero_volumes(data: tAPI.pd.DataFrame) -> bool:
        """
        Проверка свечи на аномалию связанную с нулевым объёмом при ненулевых изменениях свечи.
        
        Примеры аномалий:
          volume = 0 и closed_price - open_price != 0

        Args:
            data (_type_): Свеча, которую нужно проверить на наличие аномалии.

        Returns:
            tAPI.pd.DataFrame: Если имеется аномалия, возвращается True, иначе False.
        """
        open_, closed, volume = data.iloc[1], data.iloc[4], data.iloc[5]
        if volume == 0 and abs(open_ - closed) != 0:
            return True
        return False
    
    def detect_OHLC_anomaly(data: tAPI.pd.DataFrame) -> bool:
        """
        Проверка свечи на аномалии с Open price, Closed price, Low price, High price.
        
        Примеры аномалий:
          high price < low price | closed price | open price
          low price > high price | closed price | open_price

        Args:
            data (_type_): Свеча, которую нужно проверить на наличие аномалии.

        Returns:
            tAPI.pd.DataFrame: Если имеется аномалия, возвращается свеча с аномалией. В противном случае None
        """
        high, low, open_, closed = data.iloc[2], data.iloc[3], data.iloc[1], data.iloc[5]
        if high < max(low, closed, open_) or low > min(high, closed, open_):
            return data
        return None
    
    def detect_price_anomaly(data: tAPI.pd.DataFrame) -> bool:
        """
        Проверка свечи на аномалию с ценой (разница между LOW и MAX > 20%)

        Args:
            data (_type_): Свеча, которую нужно проверить на наличие аномалии.

        Returns:
            tAPI.pd.DataFrame: Если имеется аномалия, возвращается свеча с аномалией. В противном случае None
        """        
        high, low = data.iloc[2], data.iloc[3]
        if low > 0 and high > 0:
            if (high - low) / low > 0.2:
                return True
        return False
        
    counter_anomalies: int = 0
    for entry in data:
        if detect_OHLC_anomaly(entry):
            counter_anomalies += 1
        if detect_price_anomaly(entry):
            counter_anomalies += 1
        if detect_zero_volumes(entry):
            counter_anomalies += 1
    return counter_anomalies

for key, value in tAPI.asyncio.run(tAPI.load_multiple_candles(shoresDictionary)).items():
    print(key, value)
