#!/usr/bin/env sh
# Точка входа контейнера api (Docker):
#   1) дождаться готовности PostgreSQL;
#   2) создать/дополнить схему + демо-данные (идемпотентно, scripts/seed.py);
#   3) опционально применить alembic-миграции;
#   4) exec CMD (uvicorn).
#
# Переменные:
#   SKIP_SEED=1       — не запускать seed (БД уже наполнена отдельно)
#   RUN_MIGRATIONS=1  — применить alembic upgrade head
#   DB_WAIT_RETRIES   — сколько раз (по 2 с) ждать БД (по умолчанию 45)
set -e

log() { echo "[entrypoint] $*"; }

case "${DATABASE_URL:-}" in
  postgres*|postgresql*)
    log "ожидаю PostgreSQL..."
    DB_WAIT_RETRIES="${DB_WAIT_RETRIES:-45}" python scripts/wait_for_db.py || \
      log "БД не ответила вовремя — продолжаю, ошибка проявится при подключении"
    ;;
  *)
    log "DATABASE_URL=${DATABASE_URL:-<по умолчанию: SQLite>} — ожидание БД не требуется"
    ;;
esac

if [ "${SKIP_SEED:-0}" != "1" ]; then
  log "init_db + seed (пользователи, реестр моделей)"
  python scripts/seed.py || log "seed завершился с ошибкой — продолжаю"
else
  log "SKIP_SEED=1 — seed пропущен"
fi

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  log "alembic upgrade head"
  alembic upgrade head || log "alembic: ошибка — продолжаю"
fi

log "запуск: $*"
exec "$@"
