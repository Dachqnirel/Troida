Есть несколько методов создания СЛ и ТП:

## Проверка в коде:
```python
???
```


## Соединенные ордера:
- мы создаем 3 ордера - сама покупка, стоп-лосс и тейк-профит
- при этом ордера стоп-лосс и тейк-профит являются дочерними к основному, поэтому если он отменяется, то они отменяются тоже
- [официальная документация](https://www.backtrader.com/docu/order-creation-execution/bracket/bracket/)
```python
    def next(self):
        if self.crossover > 0:
            self.log('BUY SIGNAL')
            if not self.position:
                self.order, self.stop_loss_order, self.take_profit_order = self.buy_bracket(
                    price=self.data.close[0],
                    stopprice=self.data.close[0] * (1 - self.params.stop_loss),
                    limitprice=self.data.close[0] * (1 + self.params.take_profit),
                    size=self.calculate_trade_size()
                )
    # если происходит пересечение (наш сигнлал) и в данный момент мы не находимся в позиции, то мы создаем 3 ордера
```
