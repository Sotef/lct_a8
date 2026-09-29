#!/usr/bin/env sh
# Точка входа контейнера api (Docker):
#   0) при DEMO_DATA_HF/DEMO_DATA_URL — добрать демо-данные 2026 (панели 6ч и пр.) в /workspace;
#   1) дождаться готовности PostgreSQL;
#   2) создать/дополнить схему + демо-данные (идемпотентно, scripts/seed.py);
#   3) опционально применить alembic-миграции;
#   4) exec CMD (uvicorn).
#
# Переменные:
#   DEMO_DATA_HF=<user>/<repo>  — датасет Hugging Face с demo-data-2026.zip (скачивается без токена)
#   DEMO_DATA_URL=<URL>         — прям-ссылка на demo-data-2026.zip (Release/любой HTTPS)
#   DEMO_DATA_SHA256=<hash>     — ожидаемая контрольная сумма архива (необязательно)
#   DEMO_DATA_TIMEOUT=60        — таймаут сети на скачивание, с
#   SKIP_DEMO_FETCH=1           — вообще не трогать сеть на старте
#   SKIP_SEED=1                 — не запускать seed (БД уже наполнена отдельно)
#   RUN_MIGRATIONS=1            — применить alembic upgrade head
#   DB_WAIT_RETRIES             — сколько раз (по 2 с) ждать БД (по умолчанию 45)
set -e

log() { echo "[entrypoint] $*"; }

# --- Демо-данные 2026: панели 6ч (~319 МБ в LFS) и пр. в томе ./data ---
if [ "${SKIP_DEMO_FETCH:-0}" = "1" ]; then
  log "SKIP_DEMO_FETCH=1 — демо-данные не докачиваю"
elif [ -n "${DEMO_DATA_HF:-}" ] || [ -n "${DEMO_DATA_URL:-}" ]; then
  if python scripts/fetch_demo_data.py --check >/dev/null 2>&1; then
    log "демо-данные 2026 на месте — скачивание не требуется"
  else
    if [ -n "${DEMO_DATA_HF:-}" ]; then src="--hf ${DEMO_DATA_HF}"; else src="--url ${DEMO_DATA_URL}"; fi
    log "демо-данные неполные — получаю: fetch_demo_data.py $src"
    # shellcheck disable=SC2086
    python scripts/fetch_demo_data.py $src || \
      log "данные получить не удалось (нет сети / приватный датасет) — панель пересоберётся из raw-кэша"
  fi
fi

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
