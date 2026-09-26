# -*- coding: utf-8 -*-
"""Инференс: риск/выживаемость + RBAM-факторы (BACKEND_SPEC §5.2).

Шаг 5 цепочки:
  pr = inference_contract.predict_risk(model, subjects) -> {p24, risk30, exp_days}
  S(t) — полная кривая выживаемости (для карточки прогноза, §6.2);
  RBAM score = risk30(cal) x severity(тип) x scale(объект).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import task_cfg
from ..research_bridge import module as _m
from . import ml_registry

SEVERITY_BY_TYPE = _m("inference_contract").SEVERITY_BY_TYPE
DEFAULT_SEVERITY = _m("inference_contract").DEFAULT_SEVERITY
SCALE_COL = "каналов_активных_об_б_сум_30д"


def severity_of(channel_type) -> float:
    try:
        return float(SEVERITY_BY_TYPE.get(str(channel_type), DEFAULT_SEVERITY))
    except Exception:  # noqa: BLE001
        return DEFAULT_SEVERITY


def scale_of(n_channels_30d) -> float:
    """Масштаб объекта по числу активных каналов за 30д (эвристика v1)."""
    try:
        n = float(n_channels_30d)
    except (TypeError, ValueError):
        n = 0.0
    if n > 20:
        return 1.5
    if 6 <= n <= 20:
        return 1.25
    return 1.0


def plan_bucket(exp_days: float) -> str:
    try:
        d = float(exp_days)
    except (TypeError, ValueError):
        return "плановый"
    if d < 7:
        return "текущий квартал"
    if d < 21:
        return "следующий квартал"
    return "плановый год"


def predict_risk(task: str, subjects: pd.DataFrame) -> pd.DataFrame:
    """p24/risk30/exp_days для субъектов (через inference_contract.predict_risk)."""
    ic = _m("inference_contract")
    entry = ml_registry.get(task)
    return ic.predict_risk(entry["model"], subjects)


def predict_survival_curve(task: str, subjects: pd.DataFrame) -> np.ndarray:
    """Полная S(t) (n, 120) на 6ч-сетке 30д — для карточки прогноза."""
    tte = _m("tte_pipeline")
    entry = ml_registry.get(task)
    X_cols = entry["feature_cols"]
    X_pt, _ = tte.expand_person_time(subjects, X_cols, tte.HORIZON_BUCKETS,
                                     fixed_horizon=True)
    h = entry["model"].predict_proba(X_pt)[:, 1]
    n = len(subjects)
    return np.cumprod(1.0 - h.reshape(n, tte.HORIZON_BUCKETS), axis=1)


def surv_points_from(S: np.ndarray) -> list:
    """Точки S(t): [6ч, 12ч, 24ч, 48ч, 7д, 14д, 30д] — для карточки/UI."""
    tte = _m("tte_pipeline")
    idx = np.clip(tte.EVAL_STEPS - 1, 0, S.shape[1] - 1)
    out = S[:, idx]
    if out.ndim == 1:
        return [round(float(x), 5) for x in out]
    return [[round(float(x), 5) for x in row] for row in out]


def rbam_frame(task: str, subjects: pd.DataFrame) -> pd.DataFrame:
    """Субъекты + прогнозы + RBAM-атрибуты (severity/scale/score/plan)."""
    pr = predict_risk(task, subjects)
    out = subjects[["ид_канала_данных", "бакет", "дата", "ид_объект",
                    "тип_датчика", "event_flag", "obs_days"]].copy()
    for c in ["p24", "risk30", "exp_days"]:
        out[c] = pr[c].to_numpy()
    risk30 = out["risk30"].to_numpy(np.float64)
    out["risk_used"] = ml_registry.calibrated_risk(task, risk30)
    out["risk30_cal"] = out["risk_used"]
    out["severity"] = out["тип_датчика"].map(severity_of)
    if SCALE_COL in subjects.columns:
        out["scale"] = subjects[SCALE_COL].map(scale_of)
    else:
        out["scale"] = 1.0
    out["score"] = out["risk_used"] * out["severity"] * out["scale"]
    out["plan"] = out["exp_days"].map(plan_bucket)
    # ВАЖНО: НЕ reset_index — индекс остаётся позицией строки в subjects,
    # чтобы S(t)/SHAP/фичи выровнялись с отсортированным rb по orig-индексу.
    out = out.sort_values("score", ascending=False)
    return out