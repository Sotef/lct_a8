# -*- coding: utf-8 -*-
"""Реестр активных моделей (BACKEND_SPEC §4.1).

Загрузка моделей/калибровки выполняется один раз и кэшируется; `/admin/models/reload`
сбрасывает кэш без рестарта приложения. ML-логика вызова инкапсулирована в
research/inference_contract (здесь — только управление артефактами).
"""
from __future__ import annotations

import pathlib
import threading

import pandas as pd

from .. import config
from ..research_bridge import module as _m

_lock = threading.RLock()
_CACHE: dict[str, dict] = {}


def _model_path(task: str) -> pathlib.Path:
    return config.MODELS_DIR / f"tte_{task}_discrete_hazard.cbm"


def _calib_path(task: str) -> pathlib.Path:
    return config.MODELS_DIR / f"calib30_{task}.pkl"


def _z_stats_path(task: str) -> pathlib.Path:
    return config.DATA_DIR / f"z_stats_{task}.csv"


def _schema(task: str) -> list[str]:
    import app.services.feature_pipeline as fp
    return fp._load_features_schema().get(task, {}).get("X_cols") or []


def load_registry_task(task: str, force: bool = False) -> dict:
    """Загружает активные артефакты задачи: модель, калибровку, z-статистики, схему."""
    with _lock:
        entry = _CACHE.get(task)
        if entry is not None and not force:
            return entry
        ic = _m("inference_contract")
        model_path = _model_path(task)
        if not model_path.exists():
            raise FileNotFoundError(f"модель не найдена: {model_path}")
        model = ic.load_model(task)              # CatBoost(task_type="CPU")
        calib = ic.load_calibration(task)        # (bin_edges, rates) | None
        z_stats = pd.read_csv(_z_stats_path(task),
                              dtype={"ид_канала_данных": str}).to_dict("records")
        entry = {
            "model": model,
            "calib": calib,
            "calibrated": bool(ic.TASKS[task]["calibrated"] and calib is not None),
            "z_stats": {r["ид_канала_данных"]: (r["median"], r["iqr"])
                        for r in z_stats},
            "feature_cols": _schema(task),
            "model_path": str(model_path),
            "model_version": f"v0-2026-09-20-{task}",
        }
        _CACHE[task] = entry
        return entry


def reload_all() -> dict:
    with _lock:
        _CACHE.clear()
    loaded = {}
    for task in ["fire", "access", "sensor", "wear"]:
        try:
            load_registry_task(task, force=True)
            loaded[task] = "ok"
        except Exception as exc:  # noqa: BLE001
            loaded[task] = f"error: {exc}"
    return loaded


def get(task: str) -> dict:
    return load_registry_task(task)


def calibrated_risk(task: str, risk30) -> "pd.Series | list":
    ic = _m("inference_contract")
    entry = get(task)
    if entry["calibrated"]:
        return ic.apply_bin_map(entry["calib"], risk30)
    return ic.apply_bin_map(None, risk30)