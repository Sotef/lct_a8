# -*- coding: utf-8 -*-
"""FastAPI-приложение предиктивного сервиса (BACKEND_SPEC §0, §5)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .api import admin, auth, forecasts, health, meta, objects, risks
from .database import SessionLocal, init_db
from .research_bridge import ensure_research_importable
from .services import ml_registry, object_service
from .workers import ingestion, scheduler

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("main")


def _bootstrap_once() -> None:
    """Наполнение БД при первом запуске (справочники, L2-риски), если пусто."""
    db = SessionLocal()
    try:
        refs = object_service.load_references_into_db(db)
        n_l2 = _materialize_l2(db)
        log.info("bootstrap: refs=%s l2=%s", refs, n_l2)
    except Exception as exc:  # noqa: BLE001
        log.warning("bootstrap skipped/partially failed: %s", exc)
    finally:
        db.close()


def _materialize_l2(db) -> int:
    import pandas as pd
    fp = config.DATA_DIR / "l2_object_risk.parquet"
    if not fp.exists():
        return 0
    from . import models_db as dbm
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_research_importable()
    init_db()
    _bootstrap_once()
    # тёплый кэш моделей (CatBoost CPU) при старте
    for task in ["fire", "access", "sensor", "wear"]:
        try:
            ml_registry.load_registry_task(task)
            log.info("model loaded: %s", task)
        except Exception as exc:  # noqa: BLE001
            log.warning("model %s not ready: %s", task, exc)
    scheduler.start_scheduler(app)
    yield
    scheduler.stop_scheduler(app)


app = FastAPI(title="Москоллектор · Предиктивная аналитика ОДС",
              version="0.1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],            # frontend в dev; в проде — явный список
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api/v1"
app.include_router(health.router, prefix=API)
app.include_router(auth.router, prefix=API)
app.include_router(meta.router, prefix=API)
app.include_router(risks.router, prefix=API)
app.include_router(forecasts.router, prefix=API)
app.include_router(objects.router, prefix=API)
app.include_router(admin.router, prefix=API)

# --- Веб-интерфейс (SPA): раздаётся по «/», API-маршруты выше имеют приоритет ---
from fastapi.staticfiles import StaticFiles
from pathlib import Path as _Path

_WEB_DIR = _Path(__file__).resolve().parent / "web"
if _WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")
