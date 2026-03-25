FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY byparser.py .

RUN mkdir -p logs

EXPOSE 80

CMD ["python", "byparser.py", "--serve", "--host", "0.0.0.0", "--port", "80"]
