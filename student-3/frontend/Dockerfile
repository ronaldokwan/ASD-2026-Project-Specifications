# Student 3 - Customer Account Management - FRONTEND microservice.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_PORT=3003 \
    SHARED_DIR=/app/shared

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 3003
CMD ["gunicorn", "--bind", "0.0.0.0:3003", "--workers", "2", "--timeout", "180", "app:app"]
