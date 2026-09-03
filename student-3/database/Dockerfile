# Student 3 - Customer Account Management - DATABASE microservice.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/customers.db \
    SERVICE_PORT=9003

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 9003

CMD ["gunicorn", "--bind", "0.0.0.0:9003", "--workers", "1", "--threads", "4", "--timeout", "60", "app:app"]
