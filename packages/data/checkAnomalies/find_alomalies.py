from core.logging import logger
from abc import ABC
from pandas import DataFrame
from datetime import datetime, timedelta
import random



#     'datetime': candle.time,
#     'open': float(quotation_to_decimal(candle.open)),
#     'high': float(quotation_to_decimal(candle.high)),
#     'low': float(quotation_to_decimal(candle.low)),
#     'close': float(quotation_to_decimal(candle.close)),
#     'volume': candle.volume
# }

class CheckAnomalyCandle(ABC):
   @staticmethod
   def checkAnomalyInCandles():
       
       
    
    @staticmethod
    def createTestCandle(wrong=False):
        candle: dict = {}
        candle['datetime'] = datetime.now() - timedelta(days=random.randrange(1,366),hours=random.randrange(1, 25),minutes=random.randrange(1,60))
       
                        
    