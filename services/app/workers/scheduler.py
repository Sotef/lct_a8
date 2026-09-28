# -*- coding: utf-8 -*-
"""Планировщик прогнозов.

SIM_CLOCK=1 (по умолчанию): симулируемые часы (workers/simclock) — «сейчас»
стартует 2026-01-01 00:00 и продвигается на 6ч каждые SIM_TICK_REAL_SEC сек,
прогнозы пересчитываются в фоне (режим реплея данных 2026 года).
SIM_CLOCK=0 + RUN_SCHEDULER=1: классический 6ч-цикл по реальному времени.
"""
from __future__ import annotations

import asyncio
import logging
import os

from .. import config
from ..database import SessionLocal
from . import ingestion, simclock

log = logging.getLogger("scheduler")

_interval_sec = 6 * 3600


async def periodic_prediction_loop() -> None:
    """Пересчёт прогнозов на актуальном бакете каждые 6ч (реальное время).

    SIM_FEED=1 — каждый цикл сначала дочитывает хвост журнала СМВУ (инкрементально,
    по чекпоинту), затем пересобирает признаки и считает прогнозы: это режим
    «как в реальной работе» без реплея.
    """
    while True:
        try:
            db = SessionLocal()
            try:
                if config.SIM_FEED:
                    stat = ingestion.ingest_journal(db, year=config.SIM_YEAR)
                    log.info("stream tail ingested: %s", stat)
                res = ingestion.run_prediction_cycle(db, recompute_panel=config.SIM_FEED)
                log.info("periodic prediction done: %s", res)
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001
            log.exception("periodic prediction failed: %s", exc)
        await asyncio.sleep(_interval_sec)


def start_scheduler(app) -> None:
    if config.SIM_CLOCK:
        simclock.start()
        app.state.sim_clock = True
    elif os.environ.get("RUN_SCHEDULER", "0") == "1":
        app.state.scheduler_task = asyncio.create_task(periodic_prediction_loop())


def stop_scheduler(app) -> None:
    if getattr(app.state, "sim_clock", False):
        simclock.stop()
    task = getattr(app.state, "scheduler_task", None)
    if task is not None:
        task.cancel()