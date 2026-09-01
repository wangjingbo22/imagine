FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENVIRONMENT=production \
    AUTH_COOKIE_SECURE=true

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY backend ./backend

RUN pip install --no-cache-dir .

RUN mkdir -p /app/data

EXPOSE 8000

# Render provides the public port through PORT; locally the service remains on 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
