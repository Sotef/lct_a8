# -*- coding: utf-8 -*-
"""Симулируемые часы сервиса (режим реплея данных 2026 года).

SIM_CLOCK=1 (config): «сейчас» сервиса — симулированное время, старт 2026-01-01
00:00. Каждые SIM_TICK_REAL_SEC секунд реального времени сим-время продвигается
на 6ч (один бакет) и все 4 задачи пересчитываются на нём: прогнозы «поступают
в поток», тренд риска и KPI накапливаются в реальном времени.

Состояние (текущий сим-бакет) хранится в settings.sim_bucket и переживает рестарт.
Первый запуск с пустым sim_bucket сбрасывает старый реплей (predictions/decisions/
maintenance_tasks) и начинает с 2026-01-01 00:00.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time

import pandas as pd

from .. import config
from .. import models_db as dbm
from ..database import SessionLocal
from ..services import feature_pipeline as fp
from ..services import ml_registry, prediction_service
from . import ingestion

log = logging.getLogger("simclock")

TASKS = ("fire", "access", "sensor", "wear")
_state: dict = {
    "bucket": None, "panel_max": None, "tick_sec": config.SIM_TICK_REAL_SEC,
    "last_tick": None, "next_tick": None, "running": False,
    "computing": False, "error": None, "last_counts": None,
}
_subjects: dict = {}
_models: dict = {}
_stop = threading.Event()
_thread: threading.Thread | None = None
_db = None  # сессия текущего тика


def bucket_of(d: dt.datetime) -> int:
    """6-часовой бакет от эпохи (та же сетка, что research/features)."""
    return int((d - dt.datetime(1970, 1, 1)).total_seconds() // (6 * 3600))


def ts_of(bucket: int) -> str:
    return ingestion._bucket_ts(int(bucket)).strftime("%Y-%m-%d %H:%M")


def _settings_get(db, key: str):
    row = db.get(dbm.Setting, key)
    return row.value if row is not None else None


def _settings_set(db, key: str, value) -> None:
    row = db.get(dbm.Setting, key)
    if row is None:
        row = dbm.Setting(key=key)
        db.add(row)
    row.value = value
    db.commit()


def _fresh_start(db) -> int:
    """Сброс старого реплея и установка стартового сим-бакета (01.01.2026 00:00)."""
    start = bucket_of(dt.datetime.fromisoformat(config.SIM_START))
    n_pred = db.query(dbm.Prediction).delete()
    db.query(dbm.Decision).delete()
    db.query(dbm.MaintenanceTask).delete()
    _settings_set(db, "sim_bucket", start)
    db.commit()
    log.info("sim-clock fresh start: bucket=%s (%s), wiped predictions=%s",
             start, ts_of(start), n_pred)
    return start


def _panel_max_bucket() -> int:
    """Максимальный бакет данных в панелях (конец реплея)."""
    mx = None
    for task in TASKS:
        p = config.PANEL_DIR / f"subdaily_panel_{task}6h_2026.csv"
        if not p.exists():
            continue
        b = int(pd.read_csv(p, usecols=["бакет"])["бакет"].max())
        mx = b if mx is None else max(mx, b)
    return mx if mx is not None else bucket_of(dt.datetime(2026, 6, 30, 18))


def _warm(task: str):
    """Ленивая инициализация: модели + субъекты задачи (по одному разу)."""
    if task not in _models:
        _models[task] = ml_registry.load_registry_task(task)
    if task not in _subjects:
        _subjects[task] = fp.build_subjects(task, recompute_panel=False)


def _compute_bucket(bucket: int) -> dict:
    out = {}
    for task in TASKS:
        try:
            _warm(task)
            res = prediction_service.compute_and_store_bucket(
                task, bucket, _db, _models, subjects=_subjects[task],
                with_factors=True)
            out[task] = res.get("n_stored", 0)
        except Exception as exc:  # noqa: BLE001
            log.exception("tick %s task %s failed", bucket, task)
            out[task] = f"error: {exc}"
    return out


def _loop() -> None:
    global _db
    db = SessionLocal()
    try:
        b = _settings_get(db, "sim_bucket")
        if b is None:
            b = _fresh_start(db)
        _state["bucket"] = int(b)
    finally:
        db.close()
    _state["panel_max"] = _panel_max_bucket()
    log.info("sim-clock started: bucket=%s (%s), panel_max=%s (%s), tick=%ss",
             _state["bucket"], ts_of(_state["bucket"]), _state["panel_max"],
             ts_of(_state["panel_max"]), _state["tick_sec"])

    while not _stop.is_set():
        _state["computing"] = True
        t0 = time.time()
        try:
            _db = SessionLocal()
            counts = _compute_bucket(_state["bucket"])
            _settings_set(_db, "sim_bucket", _state["bucket"])
            _state["last_counts"] = counts
            _state["last_tick"] = time.time()
            _state["error"] = None
        except Exception as exc:  # noqa: BLE001
            log.exception("tick failed")
            _state["error"] = str(exc)
        finally:
            if _db is not None:
                _db.close()
                _db = None
            _state["computing"] = False

        if _state["bucket"] >= _state["panel_max"]:
            _state["next_tick"] = None
            _stop.wait(60)      # данные реплея закончились — idle
            continue

        _state["next_tick"] = time.time() + _state["tick_sec"]
        _stop.wait(max(1.0, _state["tick_sec"] - (time.time() - t0)))
        _state["bucket"] += 1


def _safeloop() -> None:
    """Обёртка: падение цикла фиксируется в state (видно в /meta/clock)."""
    try:
        _loop()
    except Exception:  # noqa: BLE001
        import traceback
        _state["error"] = "".join(traceback.format_exc())[-1500:]
        _state["running"] = False
        log.exception("sim-clock loop died")


def start() -> None:
    global _thread
    if _state["running"]:
        return
    _state["running"] = True
    _stop.clear()
    _thread = threading.Thread(target=_safeloop, name="sim-clock", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
    _state["running"] = False


def clock_status() -> dict:
    b = _state["bucket"]
    return {
        "mode": "replay-2026",
        "sim_now": ts_of(b) if b is not None else None,
        "bucket": b,
        "panel_max": _state["panel_max"],
        "panel_max_ts": ts_of(_state["panel_max"]) if _state["panel_max"] else None,
        "tick_sec": _state["tick_sec"],
        "next_tick_in_sec": (max(0, int(_state["next_tick"] - time.time()))
                             if _state["next_tick"] else None),
        "computing": _state["computing"],
        "last_counts": _state["last_counts"],
        "error": _state["error"],
    }
