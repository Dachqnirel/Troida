FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# requirements.txt is UTF-16 encoded; iconv (from libc-bin, pre-installed in slim) converts it to UTF-8 for pip.
# "tinkoff==0.1.1" and "tinkoff-investments==0.2.0b117" have no releases on PyPI and are not yet
# imported in the current codebase — they are future dependencies. Skip them at build time.
RUN iconv -f UTF-16 -t UTF-8 requirements.txt \
    | grep -vE '^tinkoff==|^tinkoff-investments==' \
    > requirements_utf8.txt \
 && pip install --no-cache-dir -r requirements_utf8.txt \
 && rm requirements_utf8.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
