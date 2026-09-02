# Student 4 - Jonathan Czesler - Inventory and Stock BACKEND/API microservice.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_PORT=8004

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8004

# Long timeout: an AI request may wait on the LLM through AI-Mode.
CMD ["gunicorn", "--bind", "0.0.0.0:8004", "--workers", "2", "--timeout", "180", "wsgi:app"]
