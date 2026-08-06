# syntax=docker/dockerfile:1.7

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN groupadd --system app && useradd --system --gid app app \
    && chown -R app:app /app
USER app

# Cloud Run injects $PORT (default 8080); locally we default to 8000 so
# docker-compose keeps working. exec keeps uvicorn as PID 1 for clean SIGTERM.
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}
