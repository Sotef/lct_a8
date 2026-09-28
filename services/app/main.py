# -*- coding: utf-8 -*-
"""FastAPI-приложение предиктивного сервиса (BACKEND_SPEC §0, §5)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from . import config
from .logging_setup import request_id_var, setup_logging

setup_logging()

from .api import admin, alerts, auth, forecasts, health, logs, maintenance, meta, objects, push, risks  # noqa: E402
from .database import SessionLocal, init_db  # noqa: E402
from .middleware import RequestContextMiddleware  # noqa: E402
from .research_bridge import ensure_research_importable  # noqa: E402
from .services import ml_registry, object_service  # noqa: E402
from .workers import ingestion, scheduler  # noqa: E402

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
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestContextMiddleware)   # внешний слой: request-id + access-лог


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    log.warning("validation error %s %s: %s", request.method, request.url.path,
                str(exc.errors())[:500])
    from fastapi.encoders import jsonable_encoder
    return JSONResponse(status_code=422,
                        content={"detail": jsonable_encoder(exc.errors()),
                                 "request_id": request_id_var.get()})


@app.exception_handler(Exception)
async def _unhandled_handler(request: Request, exc: Exception):
    log.exception("unhandled %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500,
                        content={"detail": "внутренняя ошибка сервера",
                                 "request_id": request_id_var.get()})


API = "/api/v1"
app.include_router(health.router, prefix=API)
app.include_router(auth.router, prefix=API)
app.include_router(meta.router, prefix=API)
app.include_router(risks.router, prefix=API)
app.include_router(forecasts.router, prefix=API)
app.include_router(objects.router, prefix=API)
app.include_router(admin.router, prefix=API)
app.include_router(maintenance.router, prefix=API)
app.include_router(alerts.router, prefix=API)
app.include_router(push.router, prefix=API)
app.include_router(logs.router, prefix=API)

# --- Веб-интерфейс (SPA): раздаётся по «/», API-маршруты выше имеют приоритет ---
import mimetypes as _mt
from fastapi.responses import FileResponse as _FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path as _Path

_mt.add_type("application/manifest+json", ".webmanifest")
_mt.add_type("image/webp", ".webp")

_WEB_DIR = _Path(__file__).resolve().parent / "web"


@app.get("/sw.js", include_in_schema=False)
def _service_worker():
    """Service worker — MOBILE_PLAN §4.4: без кэша, разрешён на корень (scope=/)."""
    return _FileResponse(_WEB_DIR / "sw.js", media_type="application/javascript",
                         headers={"Cache-Control": "no-store",
                                  "Service-Worker-Allowed": "/"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def _manifest():
    return _FileResponse(_WEB_DIR / "manifest.webmanifest",
                         media_type="application/manifest+json",
                         headers={"Cache-Control": "no-cache"})


if _WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")

    @app.middleware("http")
    async def _no_cache_ui(request, call_next):
        """UI-ассеты (js/css/html) отдаём с `no-cache`: браузер всегда ревалидирует по ETag,
        поэтому после обновления сервиса пользователь не остаётся со старым JS/CSS."""
        resp = await call_next(request)
        p = request.url.path
        if not p.startswith("/api/") and (p.endswith(".js") or p.endswith(".css")
                                          or p.endswith(".html") or p == "/"):
            resp.headers.setdefault("Cache-Control", "no-cache")
        return resp
