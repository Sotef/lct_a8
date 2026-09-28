# -*- coding: utf-8 -*-
"""Администрирование: данные, модели, drift (BACKEND_SPEC §5.3)."""
from __future__ import annotations

import logging
import platform
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models_db as dbm
from .. import task_cfg
from ..database import get_db
from ..deps import require_roles
from ..logging_setup import buffer as log_buffer
from ..research_bridge import module as _m
from ..services import audit_service, ml_registry, object_service
from ..workers import ingestion

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("admin")


@router.post("/data/load")
def data_load(tasks: list[str] | None = Query(None),
              bucket: int | None = Query(None),
              year: str = Query("2026"),
              limit_rows: int | None = Query(None,
                                             description="для теста: читать только N строк журнала"),
              db: Session = Depends(get_db),
              user: dbm.User = Depends(require_roles("central"))):
    if tasks and any(t not in task_cfg.ALL_TASKS for t in tasks):
        raise HTTPException(status_code=400, detail="неизвестная задача")
    result = {}
    ok = True
    try:
        result["journal"] = ingestion.ingest_journal(db, year=year,
                                                     limit_rows=limit_rows)
        result["prediction"] = ingestion.run_prediction_cycle(db, tasks=tasks,
                                                              bucket=bucket)
    except Exception as exc:  # noqa: BLE001
        log.exception("data_load failed")
        result["error"] = str(exc)
        ok = False
    audit_service.record(db, "admin.data_load", user_id=user.id, entity_type="data",
                         entity_id=year, detail={"tasks": tasks, "bucket": bucket,
                                                 "limit_rows": limit_rows, "ok": ok},
                         level=logging.INFO if ok else logging.ERROR)
    return {"ok": ok, "processed": result}


@router.post("/replay")
def replay(bucket_count: int = Query(40, ge=1, le=400),
           task: str | None = Query(None),
           with_factors: bool = Query(False),
           db: Session = Depends(get_db),
           user: dbm.User = Depends(require_roles("central"))):
    """Пересчёт истории прогнозов на последних N бакетах (для графиков)."""
    if task is not None and task not in task_cfg.ALL_TASKS:
        raise HTTPException(status_code=400, detail="неизвестная задача")
    tasks = [task] if task else None
    try:
        out = ingestion.run_replay(db, tasks=tasks, bucket_count=bucket_count,
                                   with_factors=with_factors)
        res = {"ok": True, "replay": out}
    except Exception as exc:  # noqa: BLE001
        log.exception("replay failed")
        res = {"ok": False, "error": str(exc)}
    audit_service.record(db, "admin.replay", user_id=user.id, entity_type="data",
                         entity_id=task or "all",
                         detail={"bucket_count": bucket_count, "ok": res["ok"]})
    return res


@router.get("/data/status")
def data_status(db: Session = Depends(get_db),
                user: dbm.User = Depends(require_roles("central", "dispatcher"))):
    rows = db.query(dbm.DataSource).all()
    return {"sources": [{"name": r.name, "kind": r.kind, "status": r.status,
                         "rows": r.rows,
                         "last_load_start": r.last_load_start.isoformat()
                         if r.last_load_start else None,
                         "last_load_end": r.last_load_end.isoformat()
                         if r.last_load_end else None,
                         "error": r.error,
                         "checkpoint": r.checkpoint} for r in rows]}


@router.post("/models/reload")
def models_reload(db: Session = Depends(get_db),
                  user: dbm.User = Depends(require_roles("central"))):
    loaded = ml_registry.reload_all()
    audit_service.record(db, "admin.models_reload", user_id=user.id, entity_type="model",
                         entity_id="all", detail={"loaded": loaded})
    return {"ok": True, "loaded": loaded}


@router.get("/models")
def models_list(db: Session = Depends(get_db),
                user: dbm.User = Depends(require_roles("central"))):
    rows = db.query(dbm.ModelRegistry).all()
    return {"models": [{"task": r.task, "version": r.version,
                        "model_path": r.model_path, "calib_path": r.calib_path,
                        "trained_on": r.trained_on, "metrics": r.metrics_json,
                        "active": r.active} for r in rows]}


@router.get("/drift")
def drift(task: str = Query(...), db: Session = Depends(get_db),
          user: dbm.User = Depends(require_roles("central"))):
    if task not in task_cfg.ALL_TASKS:
        raise HTTPException(status_code=400, detail="неизвестная задача")
    ic = _m("inference_contract")
    try:
        table = ic.risk_drift_by_quarter(task)
        return {"task": task,
                "quarters": table.to_dict(orient="records")}
    except FileNotFoundError:
        return {"task": task, "quarters": [],
                "note": "нет holdout-предсказаний (модель без отчёта)"}


@router.post("/bootstrap")
def bootstrap(db: Session = Depends(get_db),
              user: dbm.User = Depends(require_roles("central"))):
    """Загрузка справочников и L2-рисков объектов (идемпотентно)."""
    refs = object_service.load_references_into_db(db)
    _materialize_l2(db)
    audit_service.record(db, "admin.bootstrap", user_id=user.id, entity_type="data",
                         entity_id="refs", detail=refs)
    return {"ok": True, **refs}


class ClockSpeed(BaseModel):
    """Скорость демо-прокрута: уровень 1×/2×/4×/8× либо явный интервал тика."""
    level: int | None = Field(None, ge=1, le=8, description="1×/2×/4×/8× (75/40/20/10 с)")
    tick_sec: int | None = Field(None, ge=1, le=3600, description="явный интервал тика, сек")
    fast: bool | None = Field(None, description="быстрый расчёт: без SHAP-факторов")
    parallel: bool | None = Field(None, description="считать 4 задачи параллельно")


@router.post("/clock/speed")
def clock_speed(req: ClockSpeed, db: Session = Depends(get_db),
                user: dbm.User = Depends(require_roles("central"))):
    """Ускорение/замедление демо-прокрута (интервал тика, SHAP, параллельность)."""
    from ..workers import simclock
    if req.level is not None and req.tick_sec is None:
        st = simclock.set_speed_level(req.level, fast=req.fast, parallel=req.parallel)
    else:
        st = simclock.set_speed(tick_sec=req.tick_sec, fast=req.fast, parallel=req.parallel)
    audit_service.record(db, "admin.clock_speed", user_id=user.id, entity_type="clock",
                         entity_id="replay",
                         detail={"speed_level": req.level, "tick_sec": st.get("tick_sec"),
                                 "fast": st.get("fast"), "parallel": st.get("parallel")})
    return {"ok": True, "clock": st}


@router.get("/clock/speed")
def clock_speed_get(user: dbm.User = Depends(require_roles("central"))):
    from ..workers import simclock
    return {"levels": simclock.SPEED_LEVELS, "clock": simclock.clock_status()}


@router.post("/clock/reset")
def clock_reset(db: Session = Depends(get_db),
                user: dbm.User = Depends(require_roles("central"))):
    """Перезапустить реплей с SIM_START: пересчитываются только прогнозы,
    решения диспетчера, назначенные/выполненные заявки и журнал аудита сохраняются."""
    from ..workers import simclock
    st = simclock.reset()
    audit_service.record(db, "admin.clock_reset", user_id=user.id, entity_type="clock",
                         entity_id="replay", detail={"bucket": st.get("bucket"),
                                                     "sim_now": st.get("sim_now")})
    return {"ok": True, "clock": st}


@router.post("/clock/pause")
def clock_pause(db: Session = Depends(get_db),
                user: dbm.User = Depends(require_roles("central"))):
    from ..workers import simclock
    st = simclock.pause()
    audit_service.record(db, "admin.clock_pause", user_id=user.id, entity_type="clock",
                         entity_id="replay", detail={"bucket": st.get("bucket")})
    return {"ok": True, "clock": st}


@router.post("/clock/resume")
def clock_resume(db: Session = Depends(get_db),
                 user: dbm.User = Depends(require_roles("central"))):
    from ..workers import simclock
    st = simclock.resume()
    audit_service.record(db, "admin.clock_resume", user_id=user.id, entity_type="clock",
                         entity_id="replay", detail={"bucket": st.get("bucket")})
    return {"ok": True, "clock": st}


@router.post("/clock/step")
def clock_step(n: int = Query(1, ge=1, le=50),
               db: Session = Depends(get_db),
               user: dbm.User = Depends(require_roles("central"))):
    """Просчитать n бакетов вперёд немедленно (демо: «+6 ч»)."""
    from ..workers import simclock
    st = simclock.step(n)
    audit_service.record(db, "admin.clock_step", user_id=user.id, entity_type="clock",
                         entity_id="replay", detail={"n": n, "bucket": st.get("bucket")})
    return {"ok": True, "clock": st}


_STARTED_AT = time.time()


@router.get("/system")
def system(db: Session = Depends(get_db),
           user: dbm.User = Depends(require_roles("central"))):
    """Сводка состояния сервиса для страницы «Система»."""
    from sqlalchemy import func
    from .. import config
    from ..workers import simclock
    counts = {
        "predictions": db.query(func.count(dbm.Prediction.id)).scalar(),
        "decisions": db.query(func.count(dbm.Decision.id)).scalar(),
        "tickets": db.query(func.count(dbm.MaintenanceTask.id)).scalar(),
        "audit": db.query(func.count(dbm.AuditLog.id)).scalar(),
        "users": db.query(func.count(dbm.User.id)).scalar(),
        "objects": db.query(func.count(dbm.ObjectRef.id)).scalar(),
        "channels": db.query(func.count(dbm.ChannelRef.id)).scalar(),
    }
    models = {}
    for t in task_cfg.ALL_TASKS:
        try:
            ml_registry.get(t)
            models[t] = "ok"
        except Exception as exc:  # noqa: BLE001
            models[t] = f"error: {exc}"
    log_fp = config.LOG_DIR / "app.log"
    return {
        "uptime_sec": int(time.time() - _STARTED_AT),
        "python": platform.python_version(), "platform": platform.platform(),
        "db": config.DATABASE_URL.split("://")[0],
        "counts": counts, "models": models, "clock": simclock.clock_status(),
        "log": {"file": str(log_fp), "size": log_fp.stat().st_size if log_fp.exists() else 0,
                "level": config.LOG_LEVEL, "json": config.LOG_JSON,
                "buffer_last_id": log_buffer().seq},
        "auto_tickets": {"enabled": config.AUTO_TICKETS,
                         "min_risk": config.AUTO_TICKETS_MIN_RISK,
                         "top_k": config.AUTO_TICKETS_TOP_K},
    }


def _materialize_l2(db: Session) -> int:
    import pandas as pd
    from .. import config
    fp = config.DATA_DIR / "l2_object_risk.parquet"
    if not fp.exists():
        return 0
    df = pd.read_parquet(fp)
    db.query(dbm.ObjectRiskL2).delete()
    n = 0
    for _, r in df.iterrows():
        db.add(dbm.ObjectRiskL2(
            object_id=str(r["ид_объект"]), task=str(r["task"]),
            channel_count=int(r["каналов"]),
            risk30_max=float(r["risk30_max"]),
            risk30_mean=float(r["risk30_средн"]),
            top_channels=str(r["топ_каналы"])))
        n += 1
    db.commit()
    return n