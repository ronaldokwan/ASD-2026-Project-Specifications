# Student 1 - Ronaldo Kwan - Product Catalogue FRONTEND microservice (HTMX + Flask).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_PORT=3001 \
    SHARED_DIR=/app/shared

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 3001

# Timeout allows for an AI request travelling backend -> AI-Mode -> Ollama.
CMD ["gunicorn", "--bind", "0.0.0.0:3001", "--workers", "2", "--timeout", "180", "app:app"]
