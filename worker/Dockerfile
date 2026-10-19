FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
RUN pip install "psycopg[binary]==3.2.9"
COPY worker.py .
RUN useradd --uid 10001 --no-create-home shop
USER shop
CMD ["python", "worker.py"]
