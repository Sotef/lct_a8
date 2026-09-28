# -*- coding: utf-8 -*-
"""Фичи демо-прокрута: нет утечки будущего + корректная подача в модель.

Что проверяется:
1. окна/счётчики панели для бакета N не зависят от данных ПОСЛЕ N:
   панель по кэшу ≤ N совпадает по бакету N с панелью по кэшу ≤ N+130
   (130 бакетов > самой длинной оконной фичи 30д = 120 бакетов);
2. в признаки модели не попадают future-колонки (цели, дни_до_серии, _next_start_bucket);
3. признаки прокрута совпадают с X_cols обучения (имена и порядок);
4. выход модели согласован: p24 = 1−S[3], risk30 = 1−S[−1], exp_days = ΣS/4,
   повторный расчёт даёт те же значения, RBAM-скор согласован.

Пропускается, если нет сырого кэша (нужен scripts/run_demo.py).
Запуск: services\\.venv\\Scripts\\python.exe -m pytest tests/test_replay_features.py -q
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.services import feature_pipeline as fp  # noqa: E402
from app.services import inference as inf  # noqa: E402
from app.services import ml_registry  # noqa: E402

TASKS = ("fire", "access", "sensor", "wear")
RAW = config.RAW_DIR / "buckets_2026.parquet"
WINDOW_BUCKETS = 130          # > 30д (120 бакетов) — покрывает самую длинную оконную фичу
FUTURE_COLS = {"дни_до_серии", "серия_старт", "_next_start_bucket", "event_time_days",
               "obs_buckets", "obs_days", "event_flag", "дни_класс", "цель_6ч", "цель_12ч",
               "цель_24ч", "цель_48ч"} | {f"цель_серии_{k}" for k in
                                          ("6ч", "12ч", "24ч", "48ч")}
skip_no_cache = pytest.mark.skipif(not RAW.exists(), reason="нет кэша сырых бакетов")


def _cache() -> pd.DataFrame:
    return pd.read_parquet(RAW)


def _panel_for(task: str, df: pd.DataFrame, tmp: pathlib.Path) -> pd.DataFrame:
    """Панель задачи из произвольного среза сырого кэша (как делает сервис)."""
    tmp.mkdir(parents=True, exist_ok=True)
    return fp.build_subdaily_panel(task, [df.copy()],
                                   out_csv=tmp / f"subdaily_panel_{task}6h_2026.csv")


def _subjects_for(task: str, df: pd.DataFrame, tmp: pathlib.Path, bucket: int) -> pd.DataFrame:
    """Полная цепочка прокрута для одного бакета: панель → z → серии → коды → X_cols."""
    panel = _panel_for(task, df[df["бакет"] <= bucket], tmp)
    panel = fp.apply_post_task_features(panel, task)
    panel = fp.apply_train_z_stats(panel, task)
    panel = fp.apply_series_and_labels(panel, task)
    subjects = fp.align_to_schema(fp.apply_cat_codes(panel, task), task)
    return fp.subjects_for_bucket(subjects, bucket)


@skip_no_cache
def test_panel_windows_do_not_see_future():
    """Окна и счётчики бакета N одинаковы при кэше ≤N и при кэше ≤N+130.

    Из сравнения осознанно исключены:
      * `z_событий` — панель считает её по медиане/IQR ВСЕГО файла (известная
        «подглядывающая» статистика); сервис заменяет её train-статистиками на шаге 2
        (проверяется в test_z_events_uses_train_stats_only);
      * колонки-цели (`цель_6ч/12ч/24ч/48ч`) — по построению смотрят в будущее и
        вырезаются из признаков через DROP_COLS (проверяется в
        test_model_features_have_no_future_columns).
    """
    df = _cache()
    bmin, bmax = int(df["бакет"].min()), int(df["бакет"].max())
    n = bmin + 40
    assert n + WINDOW_BUCKETS <= bmax, "кэш слишком короткий для проверки окна"
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mc_leak_"))
    try:
        near = _panel_for("wear", df[df["бакет"] <= n], tmp / "near")
        far = _panel_for("wear", df[df["бакет"] <= n + WINDOW_BUCKETS], tmp / "far")
        skip = {"дата", "z_событий", "серия_старт", "дни_до_серии", "дни_класс",
                "_next_start_bucket", "event_time_days", "obs_buckets", "obs_days"}
        cols = [c for c in far.columns if c not in skip and not c.startswith("цель_")]
        assert len(cols) > 50, f"слишком мало сравниваемых колонок: {len(cols)}"
        rn = near[near["бакет"] == n].sort_values("ид_канала_данных")[cols].reset_index(drop=True)
        rf = far[far["бакет"] == n].sort_values("ид_канала_данных")[cols].reset_index(drop=True)
        assert len(rn) > 0, f"на бакете {n} нет строк панели wear"
        pd.testing.assert_frame_equal(rn, rf, check_dtype=False, rtol=1e-12)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@skip_no_cache
def test_model_input_does_not_see_future():
    """Признаки, подаваемые в модель, для бакета N не зависят от данных после N."""
    df = _cache()
    n = int(df["бакет"].min()) + 40
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mc_future_"))
    try:
        a = _subjects_for("wear", df[df["бакет"] <= n], tmp / "a", n)
        b = _subjects_for("wear", df[df["бакет"] <= n + WINDOW_BUCKETS], tmp / "b", n)
        entry = ml_registry.get("wear")
        x = list(entry["feature_cols"])
        ka = a[["ид_канала_данных"] + x].sort_values("ид_канала_данных").reset_index(drop=True)
        kb = b[["ид_канала_данных"] + x].sort_values("ид_канала_данных").reset_index(drop=True)
        assert len(ka) > 0
        pd.testing.assert_frame_equal(ka, kb, check_dtype=False, rtol=1e-12)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@skip_no_cache
def test_z_events_uses_train_stats_only():
    """`z_событий` в субъектах пересчитан по train-статистикам, а не по всему файлу."""
    df = _cache()
    n = int(df["бакет"].min()) + 40
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mc_z_"))
    try:
        rows = _subjects_for("wear", df, tmp, n)
        zs = pd.read_csv(config.DATA_DIR / "z_stats_wear.csv", dtype={"ид_канала_данных": str})
        med = dict(zip(zs["ид_канала_данных"], zs["median"]))
        iqr = dict(zip(zs["ид_канала_данных"], zs["iqr"]))
        ch = rows["ид_канала_данных"].astype(str)
        expect = (rows["событий"].to_numpy(dtype=float)
                  - ch.map(med).to_numpy(dtype=float)) / (ch.map(iqr).to_numpy(dtype=float) + 1e-6)
        np.testing.assert_allclose(rows["z_событий"].to_numpy(dtype=float), expect, atol=1e-6)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@skip_no_cache
def test_model_features_have_no_future_columns():
    """Среди признаков модели нет future-колонок (иначе модель подглядывает вперёд)."""
    schema = json.loads((config.DATA_DIR / "_features_schema.json").read_text(encoding="utf-8"))
    for task in TASKS:
        x = set(schema.get(task, {}).get("X_cols") or [])
        assert x, f"[{task}] нет X_cols в схеме фич"
        bad = x & FUTURE_COLS
        assert not bad, f"[{task}] в признаки попали future-колонки: {sorted(bad)}"


@skip_no_cache
def test_pipeline_features_equal_training_schema():
    """subject_features прокрута == X_cols обучения (имена и порядок)."""
    df = _cache()
    n = int(df["бакет"].min()) + 40
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mc_schema_"))
    try:
        rows = _subjects_for("wear", df, tmp, n)      # внутри сверяется с X_cols
        assert len(rows), f"нет субъектов на бакете {n}"
        from app.research_bridge import module as _m
        got = _m("tte_pipeline").subject_features(rows)
        entry = ml_registry.get("wear")
        assert got == list(entry["feature_cols"]), "состав/порядок фич != обучению"
        assert not (set(got) & FUTURE_COLS), "в фичи прокрута попали future-колонки"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@skip_no_cache
def test_model_output_is_consistent_and_deterministic():
    """S(t) согласована с p24/risk30/exp_days, повторный расчёт детерминирован."""
    df = _cache()
    n = int(df["бакет"].min()) + 40
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mc_inf_"))
    try:
        rows = _subjects_for("wear", df, tmp, n)
        S = inf.predict_survival_curve("wear", rows)
        pr = inf.predict_risk("wear", rows)
        assert S.shape == (len(rows), 120)
        assert np.all((S >= 0) & (S <= 1))
        assert np.all(np.diff(S, axis=1) <= 1e-9), "S(t) должна быть неубывающей по t"
        np.testing.assert_allclose(pr["p24"].to_numpy(), 1 - S[:, 3], atol=1e-9)
        np.testing.assert_allclose(pr["risk30"].to_numpy(), 1 - S[:, -1], atol=1e-9)
        np.testing.assert_allclose(pr["exp_days"].to_numpy(), S.sum(axis=1) / 4.0, atol=1e-6)
        pr2 = inf.predict_risk("wear", rows)
        np.testing.assert_allclose(pr["risk30"].to_numpy(), pr2["risk30"].to_numpy(), atol=1e-12)
        rb = inf.rbam_frame("wear", rows)
        assert len(rb) == len(rows)
        np.testing.assert_allclose(
            rb["score"].to_numpy(),
            (rb["risk_used"] * rb["severity"] * rb["scale"]).to_numpy(), atol=1e-9)
        assert rb["plan"].isin(["текущий квартал", "следующий квартал",
                                "плановый год", "плановый"]).all()
        assert rb["score"].is_monotonic_decreasing
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
