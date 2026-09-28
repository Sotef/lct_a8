# -*- coding: utf-8 -*-
"""Ингвестор: адаптер журнала -> сырой кэш -> прогнозы в БД.

Вызывается из POST /admin/data/load и планировщика. Обновляет таблицу
data_sources (статусы загрузок, checkpoint), соблюдая SLA ≤ 300 с на пачку.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from .. import config
from .. import models_db as dbm
from .. import task_cfg
from ..adapters.journal import JournalStreamAdapter
from ..research_bridge import module as _m
from ..services import feature_pipeline as fp
from ..services import ml_registry, prediction_service


def _load_journal_into_cache(year: str, limit_rows: int | None = None) -> dict:
    """Потоковый ингвест журнала (все задачи за один проход чтения)."""
    du = _m("data_utils")
    ref = du.load_ref_channels()
    union = set()
    for cfg in task_cfg.TASKS.values():
        union |= set(ref.loc[ref["тип_датчика"].isin(cfg["types"]),
                             "ид_канала_данных"])
    adapter = JournalStreamAdapter(year=year, channels=union,
                                   extra_cols=task_cfg.extra_specs(ref))
    return adapter.ingest(limit_rows=limit_rows)


def ingest_journal(db: Session, year: str = "2026",
                   limit_rows: int | None = None) -> dict:
    """Запускает адаптер журнала (инкрементально) и обновляет data_sources."""
    src = db.query(dbm.DataSource).filter(
        dbm.DataSource.name == f"journal_{year}").first()
    if src is None:
        src = dbm.DataSource(name=f"journal_{year}", kind="journal")
        db.add(src)
    src.status = "running"
    src.last_load_start = dt.datetime.now(dt.timezone.utc)
    src.error = None
    db.commit()

    try:
        started = dt.datetime.now(dt.timezone.utc)
        result = _load_journal_into_cache(year, limit_rows)
        src.rows = int(result["buckets_total"])
        src.status = "ok"
        src.last_load_end = dt.datetime.now(dt.timezone.utc)
        src.checkpoint = {"max_ts": result.get("max_ts")}
        db.commit()
        return {"year": year, **result,
                "elapsed_sec": round((src.last_load_end - started).total_seconds(), 1)}
    except Exception as exc:  # noqa: BLE001
        src.status = "error"
        src.error = str(exc)
        db.commit()
        raise


def run_prediction_cycle(db: Session, tasks: list[str] | None = None,
                         bucket: int | None = None,
                         recompute_panel: bool = False) -> dict:
    """Полный цикл: субъекты -> прогноз -> БД для задач (по умолчанию — все 4)."""
    tasks = tasks or task_cfg.ALL_TASKS
    models = {t: ml_registry.load_registry_task(t) for t in tasks}
    result = {}
    # бакет «сейчас»: максимум по доступному кэшу (2026-06-30 18:00 в тесте)
    if bucket is None:
        subject = fp.build_subjects(tasks[0], recompute_panel=recompute_panel)
        bucket = fp.latest_bucket(subject)
    for task in tasks:
        started = dt.datetime.now(dt.timezone.utc)
        try:
            res = prediction_service.compute_and_store_bucket(
                task, bucket, db, recompute_panel=recompute_panel,
                model_holder=models)
            res["elapsed_sec"] = round(
                (dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 1)
            result[task] = res
        except Exception as exc:  # noqa: BLE001
            result[task] = {"error": str(exc)}
    if config.ALERTS_PUSH:
        try:
            from . import alerts as alerts_worker
            result["alerts"] = alerts_worker.run(db)
        except Exception as exc:  # noqa: BLE001
            result["alerts"] = {"error": str(exc)}
    return {"bucket": bucket, "results": result}


def run_replay(db: Session, tasks: list[str] | None = None,
               bucket_count: int | None = None,
               recompute_panel: bool = False,
               with_factors: bool = False) -> dict:
    """Пересчёт прогнозов на последних N бакетах (история для графиков «as-of»).

    Субъекты собираются ОДИН раз на задачу, затем считаются бакеты от последнего
    вниз. bucket_count=None — все доступные бакеты панели.
    """
    tasks = tasks or task_cfg.ALL_TASKS
    models = {t: ml_registry.load_registry_task(t) for t in tasks}
    outcome = {}
    for task in tasks:
        started = dt.datetime.now(dt.timezone.utc)
        try:
            subjects = fp.build_subjects(task, recompute_panel=recompute_panel)
            all_buckets = sorted(subjects["бакет"].unique().tolist())
            if bucket_count:
                all_buckets = all_buckets[-int(bucket_count):]
            per = {}
            for b in all_buckets:
                res = prediction_service.compute_and_store_bucket(
                    task, int(b), db, models, subjects=subjects,
                    with_factors=with_factors)
                per[int(b)] = {"n": res["n_stored"],
                               "ts": str(_bucket_ts(int(b)))}
            outcome[task] = {
                "bucket_count": len(all_buckets),
                "first": str(_bucket_ts(int(all_buckets[0]))) if all_buckets else None,
                "last": str(_bucket_ts(int(all_buckets[-1]))) if all_buckets else None,
                "elapsed_sec": round((dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 1),
                "buckets": per,
            }
        except Exception as exc:  # noqa: BLE001
            outcome[task] = {"error": str(exc)}
    return outcome


def _bucket_ts(bucket: int):
    from ..adapters.journal import bucket_to_timestamp
    import pandas as pd
    return pd.Timestamp(bucket_to_timestamp(bucket))