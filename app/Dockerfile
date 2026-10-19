FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prom

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py gunicorn.conf.py entrypoint.sh ./
RUN chmod +x entrypoint.sh \
 && useradd --uid 10001 --no-create-home shop
USER shop

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
