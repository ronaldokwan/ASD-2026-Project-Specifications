# Student 5 - Alexander McGuinn - Reviews and Ratings DATABASE microservice (SQLite).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/reviews.db \
    SERVICE_PORT=9005

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The database file lives on a named volume so data survives container restarts.
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 9005

# One worker: SQLite is single-writer, and this service is only called by the
# Student 5 backend/API microservice.
CMD ["gunicorn", "--bind", "0.0.0.0:9005", "--workers", "1", "--threads", "4", "--timeout", "60", "app:app"]
