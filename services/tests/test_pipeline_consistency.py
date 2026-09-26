# -*- coding: utf-8 -*-
"""Согласованность панели/субъектов с обучением (по реальному кэшу 2026).

Пропускается, если сырой кэш ещё не собран (требуется хотя бы один
scripts/run_demo.py --limit ...).
"""
from __future__ import annotations

import pathlib
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.services import feature_pipeline as fp  # noqa: E402
from app.services import ml_registry  # noqa: E402


def _cache_available() -> bool:
    return (config.RAW_DIR / "buckets_2026.parquet").exists()


pytestmark = pytest.mark.skipif(not _cache_available(),
                                reason="нет кэша сырых бакетов (сначала run_demo.py)")


@pytest.mark.parametrize("task", ["fire", "access", "sensor", "wear"])
def test_subject_features_match_schema(task):
    subjects = fp.build_subjects(task)
    cols = _m("tte_pipeline").subject_features(subjects)
    schema = _load_schema(task)
    assert cols == schema, f"[{task}] X_cols != схема обучения"


@pytest.mark.parametrize("task", ["fire", "access", "sensor", "wear"])
def test_derived_features_present(task):
    panel = pd.read_csv(config.PANEL_DIR / f"subdaily_panel_{task}6h_2026.csv",
                        dtype={"ид_канала_данных": str, "ид_объект": str})
    if task == "fire":
        assert "серьёзных" in panel.columns and "задым_подтв_об_б" in panel.columns
    if task == "access":
        assert "дверь_движение_об_б" in panel.columns


def test_predictions_non_nan_on_latest_bucket():
    from app.services import inference as inf
    for task in ["wear", "fire"]:
        sub = fp.build_subjects(task)
        bucket = fp.latest_bucket(sub)
        rows = fp.subjects_for_bucket(sub, bucket)
        if not len(rows):
            continue
        pr = inf.predict_risk(task, rows)
        assert pr["p24"].notna().all()
        assert pr["risk30"].notna().all()
        assert pr["exp_days"].notna().all()


def _m(name):
    from app.research_bridge import module as m
    return m(name)


def _load_schema(task):
    return ml_registry.get(task)["feature_cols"]