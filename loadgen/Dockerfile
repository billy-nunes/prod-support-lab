FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /srv
COPY loadgen.py .
RUN useradd --uid 10001 --no-create-home shop
USER shop
CMD ["python", "loadgen.py"]
