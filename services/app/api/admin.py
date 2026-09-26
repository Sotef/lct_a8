# -*- coding: utf-8 -*-
"""Администрирование: данные, модели, drift (BACKEND_SPEC §5.3)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models_db as dbm
from .. import task_cfg
from ..database import get_db
from ..deps import require_roles
from ..research_bridge import module as _m
from ..services import ml_registry, object_service
from ..workers import ingestion

router = APIRouter(prefix="/admin", tags=["admin"])


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
    try:
        result["journal"] = ingestion.ingest_journal(db, year=year,
                                                     limit_rows=limit_rows)
    except Exception as exc:  # noqa: BLE001
        result["journal"] = {"error": str(exc)}
        return {"ok": False, "processed": result}
    try:
        result["prediction"] = ingestion.run_prediction_cycle(db, tasks=tasks,
                                                              bucket=bucket)
    except Exception as exc:  # noqa: BLE001
        result["prediction"] = {"error": str(exc)}
        return {"ok": False, "processed": result}
    return {"ok": True, "processed": result}


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
        return {"ok": True, "replay": out}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


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
    return {"ok": True, **refs}


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