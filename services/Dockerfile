# Этап сборки (зависимости приложения)
FROM python:3.12-slim

WORKDIR /workspace/services
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY alembic.ini .
COPY alembic ./alembic
COPY .env.example .env

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]