# Student 1 - Ronaldo Kwan - Product Catalogue BACKEND/API microservice.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_PORT=8001

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

# Long timeout: an AI request may wait on the LLM through AI-Mode.
CMD ["gunicorn", "--bind", "0.0.0.0:8001", "--workers", "2", "--timeout", "180", "wsgi:app"]
