# Backend image: Python 3.12 slim + FastAPI on uvicorn.
# Runs identically locally (docker compose) and on Cloud Run.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Dependencies first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data
COPY evals ./evals
COPY pytest.ini .

EXPOSE 8080

# Cloud Run injects PORT; default 8080 matches local compose.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
