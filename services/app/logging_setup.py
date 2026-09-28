# -*- coding: utf-8 -*-
"""Структурное логирование сервиса.

- консоль: человекочитаемый формат;
- файл  : services/logs/app.log — JSON lines, ротация (LOG_FILE_MAX_MB × LOG_FILE_BACKUPS);
- буфер : кольцевой буфер в памяти (последние LOG_BUFFER_SIZE записей) — live-просмотр
          в веб-интерфейсе (GET /api/v1/admin/logs).

Контекст запроса (request_id, пользователь, ip) прокидывается через contextvars
(см. app/middleware.py) и автоматически попадает в каждую запись.
"""
from __future__ import annotations

import collections
import contextvars
import datetime as dt
import json
import logging
import logging.handlers
import threading

from . import config

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
user_var: contextvars.ContextVar[str] = contextvars.ContextVar("user", default="-")
client_ip_var: contextvars.ContextVar[str] = contextvars.ContextVar("client_ip", default="-")

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="milliseconds")


class ContextFilter(logging.Filter):
    """Добавляет request_id/user/ip в каждую запись."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.user = user_var.get()
        record.client_ip = client_ip_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": _iso(record.created), "level": record.levelname,
             "logger": record.name, "msg": record.getMessage(),
             "request_id": getattr(record, "request_id", "-"),
             "user": getattr(record, "user", "-"),
             "ip": getattr(record, "client_ip", "-")}
        data = getattr(record, "extra_data", None)
        if data:
            d["data"] = data
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
        return json.dumps(d, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    def __init__(self):
        super().__init__("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        rid = getattr(record, "request_id", "-")
        return f"{base} (rid={rid})" if rid and rid != "-" else base


class RingBufferHandler(logging.Handler):
    """Последние N записей в памяти (для live-просмотра в UI)."""

    def __init__(self, capacity: int):
        super().__init__()
        self.buf: collections.deque = collections.deque(maxlen=capacity)
        self.seq = 0
        self._buf_lock = threading.Lock()
        self._exc_fmt = logging.Formatter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            msg = str(record.msg)
        item = {"ts": _iso(record.created), "level": record.levelname,
                "levelno": record.levelno, "logger": record.name, "msg": msg[:4000],
                "request_id": getattr(record, "request_id", "-"),
                "user": getattr(record, "user", "-"),
                "ip": getattr(record, "client_ip", "-"),
                "data": getattr(record, "extra_data", None)}
        if record.exc_info:
            item["exc"] = self._exc_fmt.formatException(record.exc_info)[-4000:]
        with self._buf_lock:
            self.seq += 1
            item["id"] = self.seq
            self.buf.append(item)

    def query(self, after_id: int = 0, level: str | None = None,
              logger: str | None = None, q: str | None = None,
              limit: int = 300) -> dict:
        min_lv = _LEVELS.get((level or "").upper(), 0)
        term = (q or "").lower()
        with self._buf_lock:
            items = list(self.buf)
            last = self.seq
        out = []
        for it in items:
            if it["id"] <= after_id or it["levelno"] < min_lv:
                continue
            if logger and not it["logger"].startswith(logger):
                continue
            if term and term not in (it["msg"] + " " + it["logger"] + " "
                                     + str(it.get("user"))).lower():
                continue
            out.append(it)
        return {"items": out[-limit:], "last_id": last}


_buffer: RingBufferHandler | None = None
_configured = False


def setup_logging() -> None:
    """Идемпотентная настройка логирования (вызывается при импорте app.main)."""
    global _buffer, _configured
    if _configured:
        return
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(_LEVELS.get(config.LOG_LEVEL.upper(), logging.INFO))
    for h in list(root.handlers):          # убираем basicConfig-хендлеры
        root.removeHandler(h)

    ctx = ContextFilter()
    console = logging.StreamHandler()
    console.setFormatter(ConsoleFormatter())
    console.addFilter(ctx)

    file_h = logging.handlers.RotatingFileHandler(
        config.LOG_DIR / "app.log", maxBytes=config.LOG_FILE_MAX_MB * 1024 * 1024,
        backupCount=config.LOG_FILE_BACKUPS, encoding="utf-8", delay=True)
    file_h.setFormatter(JsonFormatter() if config.LOG_JSON else ConsoleFormatter())
    file_h.addFilter(ctx)

    _buffer = RingBufferHandler(config.LOG_BUFFER_SIZE)
    _buffer.addFilter(ctx)

    for h in (console, file_h, _buffer):
        root.addHandler(h)
    # ошибки/старт uvicorn тоже в файл и буфер (у uvicorn propagate=False)
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.addHandler(file_h)
        lg.addHandler(_buffer)
    # uvicorn.access дублирует наш access-лог — глушим
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    for name in ("sqlalchemy.engine", "httpx", "multipart", "watchfiles"):
        logging.getLogger(name).setLevel(logging.WARNING)
    _configured = True


def buffer() -> RingBufferHandler:
    if _buffer is None:
        setup_logging()
    return _buffer  # type: ignore[return-value]


def log_event(logger: logging.Logger, level: int, msg: str, **data) -> None:
    """Запись со структурированными полями (попадают в JSON как "data").

    Ключи, совпадающие с параметрами функции (`level`, `msg`, `logger`), переименовываются,
    иначе вызов падает с «got multiple values for argument».
    """
    for k in ("level", "msg", "logger"):
        if k in data:
            data["log_" + k] = data.pop(k)
    logger.log(level, msg, extra={"extra_data": data or None})
