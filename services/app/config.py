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


def ensure_dirs() -> None:
    for d in (DATA_DIR, RAW_DIR, PANEL_DIR, EXTRA_DIR):
        d.mkdir(parents=True, exist_ok=True)


ensure_dirs()