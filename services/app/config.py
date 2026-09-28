# -*- coding: utf-8 -*-
"""Конфигурация сервиса (единая точка настроек)."""
from __future__ import annotations

import os
import pathlib

from dotenv import load_dotenv

SERVICES_DIR = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(SERVICES_DIR / ".env", override=False)


def _p(key: str, default: str) -> pathlib.Path:
    return pathlib.Path(os.getenv(key, default))


# --- Пути данных -------------------------------------------------------------
RESEARCH_DIR = _p("RESEARCH_DIR", r"d:\Downloads_D\lct_a8\research")
DATASET_DIR = _p("DATASET_DIR", str(RESEARCH_DIR / "dataset"))
EXTRACTED_DIR = _p("EXTRACTED_DIR", str(DATASET_DIR / "extracted"))
MODELS_DIR = _p("MODELS_DIR", str(RESEARCH_DIR / "models"))
DATA_DIR = SERVICES_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PANEL_DIR = DATA_DIR / "panels"
EXTRA_DIR = DATA_DIR / "_external"          # кэш внешних адаптеров (read-only копии)

# --- БД ----------------------------------------------------------------------
# По умолчанию SQLite (локальная разработка); в проде — PostgreSQL 12+:
#   DATABASE_URL=postgresql://user:pass@localhost:5432/moscollector_api
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'app.db'}")
SQLITE_RETRIES = int(os.getenv("SQLITE_RETRIES", "20"))   # busy timeout, сек
DB_ECHO = os.getenv("DB_ECHO", "0") == "1"

# --- Безопасность --------------------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "30"))
REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "7"))
LOGIN_RATE_LIMIT = int(os.getenv("LOGIN_RATE_LIMIT", "20"))      # попыток на 5 мин

# --- ML/инференс ----------------------------------------------------------------
HORIZON_DAYS = 30.0
BUCKET_HOURS = 6
STEPS_PER_DAY = 24 // BUCKET_HOURS          # 4
HORIZON_BUCKETS = int(HORIZON_DAYS * STEPS_PER_DAY)  # 120

# Порт/хост API
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

# Файл журнала СМВУ для потоковой подачи на тесте (заглушка): только 2026.
STREAM_SOURCE = _p("STREAM_SOURCE", str(EXTRACTED_DIR / "ext-journal-2026.csv"))

# --- Симулируемые часы (режим реплея данных 2026 года) -------------------------
# SIM_CLOCK=1: «сейчас» сервиса = симулированное время, старт 2026-01-01 00:00;
# каждые SIM_TICK_REAL_SEC секунд реального времени сим-время продвигается на
# 6ч (один бакет) и все 4 задачи пересчитываются. Прогнозы попадают в сезонность.
SIM_CLOCK = os.getenv("SIM_CLOCK", "1") == "1"
SIM_START = os.getenv("SIM_START", "2026-01-01T00:00:00")
SIM_TICK_REAL_SEC = int(os.getenv("SIM_TICK_REAL_SEC", "75"))
# SIM_LOOP=1: дойдя до конца периода (panel_max), реплей начинается заново с SIM_START
# (прогнозы/решения/заявки предыдущего круга сбрасываются) — демо живёт бесконечно.
SIM_LOOP = os.getenv("SIM_LOOP", "1") == "1"


# --- Логирование -----------------------------------------------------------------
LOG_DIR = _p("LOG_DIR", str(SERVICES_DIR / "logs"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_JSON = os.getenv("LOG_JSON", "1") == "1"                 # JSON lines в файле
LOG_FILE_MAX_MB = int(os.getenv("LOG_FILE_MAX_MB", "20"))
LOG_FILE_BACKUPS = int(os.getenv("LOG_FILE_BACKUPS", "5"))
LOG_BUFFER_SIZE = int(os.getenv("LOG_BUFFER_SIZE", "3000"))  # live-буфер для UI
SLOW_REQUEST_MS = int(os.getenv("SLOW_REQUEST_MS", "1500"))  # порог WARNING
# Автоформирование превентивных заявок на каждом сим-тике/цикле прогноза
AUTO_TICKETS = os.getenv("AUTO_TICKETS", "1") == "1"
AUTO_TICKETS_MIN_RISK = float(os.getenv("AUTO_TICKETS_MIN_RISK", "0.5"))
AUTO_TICKETS_TOP_K = int(os.getenv("AUTO_TICKETS_TOP_K", "15"))

# Сколько каналов на задачу получают SHAP-факторы «почему» (самое дорогое место
# тика: ~43 с на задачу при 400). Уменьшение ускоряет прокрут, но карточки
# каналов ниже топ-N будут без факторов.
SHAP_TOP_K = int(os.getenv("SHAP_TOP_K", "400"))

# --- Мобильная версия / PWA (MOBILE_PLAN §6.2) ---------------------------------
PWA = os.getenv("PWA", "1") == "1"                     # отдавать manifest/SW, включать клиентские фичи
ALERTS_PUSH = os.getenv("ALERTS_PUSH", "1") == "1"     # серверное правило алертов + рассылка
ALERTS_MIN_P7D = float(os.getenv("ALERTS_MIN_P7D", "0.2"))
ALERTS_SILENCE_HOURS = int(os.getenv("ALERTS_SILENCE_HOURS", "12"))
ALERTS_QUIET_FROM = os.getenv("ALERTS_QUIET_FROM", "")  # «тихие часы» HH:MM (опционально)
ALERTS_QUIET_TO = os.getenv("ALERTS_QUIET_TO", "")
ALERTS_TOP_K = int(os.getenv("ALERTS_TOP_K", "50"))    # сколько алертов за тик рассматривать

# Web Push (VAPID). Пусто -> push-subscribe работает, но рассылка — no-op,
# клиент откатывается на фолбэк-поллинг /alerts (см. MOBILE_PLAN §4.6).
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:ods@moscollector.ru")

# Сессия мобильного профиля (обновление токена живёт дольше на телефоне)
MOBILE_REFRESH_DAYS = int(os.getenv("MOBILE_REFRESH_DAYS", "30"))
AUTH_COOKIE_REFRESH = os.getenv("AUTH_COOKIE_REFRESH", "0") == "1"

# Вложения (фото с объекта)
ATTACH_DIR = _p("ATTACH_DIR", str(DATA_DIR / "attachments"))
ATTACH_MAX_MB = int(os.getenv("ATTACH_MAX_MB", "5"))


def ensure_dirs() -> None:
    for d in (DATA_DIR, RAW_DIR, PANEL_DIR, EXTRA_DIR, LOG_DIR, ATTACH_DIR):
        d.mkdir(parents=True, exist_ok=True)


ensure_dirs()