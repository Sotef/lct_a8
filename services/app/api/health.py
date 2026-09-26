# -*- coding: utf-8 -*-
"""Health-ручка."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..services import ml_registry

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    status_models = {}
    for task in ["fire", "access", "sensor", "wear"]:
        try:
            ml_registry.get(task)
            status_models[task] = "ok"
        except Exception as exc:  # noqa: BLE001
            status_models[task] = f"error: {exc}"
    return {"status": "ok", "model_version": "v0-2026-09-20",
            "models": status_models}