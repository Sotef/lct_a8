# Предиктивный сервис АО «Москоллектор» — образ API (Python 3.12, FastAPI/uvicorn).
# Сборка: docker compose build
#
# Важно: research-каталог (модели + справочники + журналы) НЕ копируется в образ —
# он подключается read-only volume-ом (см. docker-compose.yml), т.к. содержит
# десятки ГБ исторических выгрузок СМВУ.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/workspace/services \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /workspace/services

# Системные зависимости:
#  - libgomp1  — runtime CatBoost (OpenMP)
#  - curl      — HEALTHCHECK
#  - ca-certificates — HTTPS-интеграции (LDAP/AD, Web Push)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY alembic.ini ./
COPY alembic ./alembic

# Каталоги, которые перекрываются volume-ами (создаём, чтобы работало и без них);
# sed — нормализуем CRLF у entrypoint (файл мог быть сохранён в Windows)
RUN mkdir -p /workspace/services/data/attachments /workspace/services/logs \
    && sed -i 's/\r$//' scripts/docker-entrypoint.sh \
    && useradd -r -u 10001 -m appuser \
    && chown -R appuser:appuser /workspace

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=6s --start-period=90s --retries=5 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/v1/health" || exit 1

# ENTRYPOINT: ожидание БД + seed (идемпотентно) + запуск CMD
ENTRYPOINT ["sh", "scripts/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
