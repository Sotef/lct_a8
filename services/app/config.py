# -*- coding: utf-8 -*-
"""Конфигурация сервиса (единая точка настроек)."""
from __future__ import annotations

import json as _json
import os
import pathlib

from dotenv import load_dotenv

SERVICES_DIR = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(SERVICES_DIR / ".env", override=False)


def _p(key: str, default: str) -> pathlib.Path:
    return pathlib.Path(os.getenv(key, default))


# --- Пути данных -------------------------------------------------------------
# Пути данных: по умолчанию research лежит рядом с services/ (портативно — от расположения репо),
# переменная RESEARCH_DIR нужна только если research вынесен в другое место
RESEARCH_DIR = _p("RESEARCH_DIR", str(SERVICES_DIR.parent / "research"))
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
# Год данных журнала, на котором работает сервис (файл ext-journal-<год>.csv)
SIM_YEAR = os.getenv("SIM_YEAR", "2026")
SIM_START = os.getenv("SIM_START", "2026-01-01T00:00:00")
SIM_TICK_REAL_SEC = int(os.getenv("SIM_TICK_REAL_SEC", "75"))
# SIM_LOOP=1: дойдя до конца периода (panel_max), реплей начинается заново с SIM_START
# (прогнозы/решения/заявки предыдущего круга сбрасываются) — демо живёт бесконечно.
SIM_LOOP = os.getenv("SIM_LOOP", "1") == "1"

# --- Живая подача данных из журнала (как в реальной работе) ---------------------
# SIM_FEED=1: на каждом тике сервис сам читает НОВЫЙ ХВОСТ грязного ext-journal-*.csv,
# агрегирует его (adapters/journal), пересобирает признаки/панель из накопленного кэша
# и инференсит текущий бакет. Предзагруженные панели research/dataset при этом не
# используются: кэш и панели живут в отдельном каталоге STREAM_DIR.
SIM_FEED = os.getenv("SIM_FEED", "0") == "1"
# Читать журнал порциями (строк за один read_csv), SIM_FEED_CHUNK
SIM_FEED_CHUNK = int(os.getenv("SIM_FEED_CHUNK", "200000"))
# Конец периода подачи (ISO-дата/время). Пусто -> определяется по последней строке журнала.
SIM_FEED_END = os.getenv("SIM_FEED_END", "")
# Пересобирать признаки на каждом тике (для режима подачи — обязательно)
SIM_FEED_REBUILD = os.getenv("SIM_FEED_REBUILD", "1") == "1"
# SIM_FEED_WARMUP=1: перед стартом подачи «дочитать» журнал до SIM_START, чтобы у признаков
# была история (иначе первые бакеты — холодный старт). Данные после SIM_START не берутся.
SIM_FEED_WARMUP = os.getenv("SIM_FEED_WARMUP", "1") == "1"

# Каталог «живой подачи»: отдельный кэш/панели, чтобы не смешивать с предзагруженными
# данными research. В режиме SIM_FEED сервис читает журнал и строит признаки сам.
STREAM_DIR = DATA_DIR / "stream"
if SIM_FEED:
    RAW_DIR = STREAM_DIR / "raw"
    PANEL_DIR = STREAM_DIR / "panels"


# --- Логирование -----------------------------------------------------------------
LOG_DIR = _p("LOG_DIR", str(SERVICES_DIR / "logs"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_JSON = os.getenv("LOG_JSON", "1") == "1"                 # JSON lines в файле
LOG_FILE_MAX_MB = int(os.getenv("LOG_FILE_MAX_MB", "20"))
LOG_FILE_BACKUPS = int(os.getenv("LOG_FILE_BACKUPS", "5"))
LOG_BUFFER_SIZE = int(os.getenv("LOG_BUFFER_SIZE", "3000"))  # live-буфер для UI
SLOW_REQUEST_MS = int(os.getenv("SLOW_REQUEST_MS", "1500"))  # порог WARNING
# Автоформирование превентивных заявок на каждом сим-тике/цикле прогноза.
#
# Приоритизация (см. README «План ТО: как приоритизируются заявки»):
#   * порог по вероятности — свой для задачи (`AUTO_TICKETS_MIN_RISK_BY_TASK`):
#     у моделей разная шкала (только `access` калибрована, у fire/wear вероятности
#     крупнее) — единый порог сравнивал бы несравнимое;
#   * порог ослабляется по классу последствия: чем тяжелее тип датчика
#     (severity, SEVERITY_MAP v1), тем при меньшей вероятности заводим заявку:
#     eff = base_task × (SEVERITY_REF / severity);
#   * ограничение — не «слепой top-K до дедупа», а ресурс: не больше
#     `AUTO_TICKETS_TOP_K` новых заявок за тик и не больше `AUTO_TICKETS_NEAR_CAP`
#     открытых near-term заявок на задачу (иначе очередь не отработать).
AUTO_TICKETS = os.getenv("AUTO_TICKETS", "1") == "1"
AUTO_TICKETS_MIN_RISK = float(os.getenv("AUTO_TICKETS_MIN_RISK", "0.5"))  # fallback
AUTO_TICKETS_TOP_K = int(os.getenv("AUTO_TICKETS_TOP_K", "60"))           # ёмкость за тик
_BY_TASK_DEFAULT = {"fire": 0.30, "access": 0.45, "sensor": 0.45, "wear": 0.50}
if os.getenv("AUTO_TICKETS_MIN_RISK") is not None:
    # явный env-порог трактуем как единый base для всех направлений
    AUTO_TICKETS_MIN_RISK_BY_TASK = {t: AUTO_TICKETS_MIN_RISK for t in _BY_TASK_DEFAULT}
else:
    try:
        AUTO_TICKETS_MIN_RISK_BY_TASK = _json.loads(os.getenv(
            "AUTO_TICKETS_MIN_RISK_BY_TASK", _json.dumps(_BY_TASK_DEFAULT)))
    except ValueError:
        AUTO_TICKETS_MIN_RISK_BY_TASK = dict(_BY_TASK_DEFAULT)
AUTO_TICKETS_SEVERITY_REF = float(os.getenv("AUTO_TICKETS_SEVERITY_REF", "0.6"))
AUTO_TICKETS_NEAR_CAP = int(os.getenv("AUTO_TICKETS_NEAR_CAP", "500"))
# Плановые даты: гистерезис (не двигаем срок открытой заявки при мелких сдвигах)
# и потолок «прогнозного срока» (дней), чтобы min(прогноз, норматив) был осмысленным.
PLAN_HYSTERESIS_DAYS = int(os.getenv("PLAN_HYSTERESIS_DAYS", "5"))
PLAN_FORECAST_CAP_DAYS = int(os.getenv("PLAN_FORECAST_CAP_DAYS", "90"))

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
    for d in (DATA_DIR, RAW_DIR, PANEL_DIR, EXTRA_DIR, LOG_DIR, ATTACH_DIR,
              STREAM_DIR, STREAM_DIR / "raw", STREAM_DIR / "panels"):
        d.mkdir(parents=True, exist_ok=True)


ensure_dirs()