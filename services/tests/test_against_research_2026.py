# -*- coding: utf-8 -*-
"""Сквозная сверка «поток → формат модели» с ground truth research (по 2026 году).

Главный тест корректности подачи данных: сервисный потоковый кэш
(`services/data/raw/buckets_2026.parquet`, собран из ext-journal-2026.csv)
сравнивается ПОЭЛЕМЕНТНО с research-панелями (subdaily_panel_*.csv), которые
использовались при обучении. Проверяется, что сервисная агрегация «канал × 6ч
бакет» даёт те же счётчики (событий/тревог/неисправностей/шума + все
extra_cols задач: задымлений, серьёзн_ручной, тревог_дым/тепло/дверь/движение,
пр_разрывов, неисправн_дым), что и research `_aggregate_bucket_year`.

wear/fire — ПОЛНАЯ сверка всех ключей 2026; access/sensor — сверка на выборке
ключей (панель sensor ~1.9 ГБ, чтобы держать время теста в разумных рамках).

Запуск: services\\.venv\\Scripts\\python.exe -m pytest tests/test_against_research_2026.py -q
"""
from __future__ import annotations

import pathlib
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.research_bridge import module as _m  # noqa: E402

HOUR_NS = 6 * 3600 * 10 ** 9
B_MIN = int(pd.Timestamp("2026-01-01").value) // HOUR_NS
B_MAX = int(pd.Timestamp("2026-07-02").value) // HOUR_NS  # всё H1-2026

# Счётчики для сверки: базовые + extra_cols задачи (сырые, per-channel)
COUNT_COLS = {
    "wear": ["событий", "тревог", "неисправностей", "шума"],
    "fire": ["событий", "тревог", "неисправностей", "шума",
             "задымлений", "серьёзн_ручной", "тревог_дым", "тревог_тепло"],
    "access": ["событий", "тревог", "неисправностей", "шума",
               "тревог_дверь", "тревог_движение"],
    "sensor": ["событий", "тревог", "неисправностей", "шума",
               "пр_разрывов", "неисправн_дым"],
}
FULL_CHECK = {"wear", "fire"}          # полная сверка ключей
SAMPLE_KEYS = 2000                     # выборка для access/sensor

PANEL_COL = {  # research-панель задачи
    "wear": "subdaily_panel_wear_6h.csv",
    "fire": "subdaily_panel_fire6h.csv",
    "access": "subdaily_panel_access6h.csv",
    "sensor": "subdaily_panel_sensor6h.csv",
}


def _service_counts(task: str, keys_only: set | None = None) -> dict:
    """Счётчики сервисного потокового кэша за 2026: {(ch, бакет): tuple(counts)}."""
    cache = pd.read_parquet(config.RAW_DIR / "buckets_2026.parquet")
    cache = cache[(cache["бакет"] >= B_MIN) & (cache["бакет"] <= B_MAX)]
    ch_set = _task_channels(task)
    cache = cache[cache["ид_канала_данных"].isin(ch_set)]
    if keys_only is not None:
        kdf = pd.DataFrame(list(keys_only), columns=["ид_канала_данных", "бакет"])
        cache = cache.merge(kdf, on=["ид_канала_данных", "бакет"], how="inner")
    g = (cache.groupby(["ид_канала_данных", "бакет"], sort=False)
         [COUNT_COLS[task]].sum())
    return {k: tuple(int(x) for x in v) for k, v in g.iterrows()}


def _research_counts(task: str, keys_only: set | None = None) -> dict:
    """Счётчики research-панели (ground truth) за 2026, чтение чанками."""
    fp = _m("features").DATASET / PANEL_COL[task]
    if not fp.exists():
        pytest.skip(f"нет research-панели: {fp}")
    cols = ["ид_канала_данных", "бакет"] + COUNT_COLS[task]
    agg: dict = {}
    for chunk in pd.read_csv(fp, usecols=cols, dtype={"ид_канала_данных": str},
                             encoding="utf-8-sig", chunksize=500_000):
        chunk = chunk[(chunk["бакет"] >= B_MIN) & (chunk["бакет"] <= B_MAX)]
        if keys_only is not None:
            chunk = chunk.set_index(["ид_канала_данных", "бакет"])
            chunk = chunk[chunk.index.isin(keys_only)].reset_index()
        if not len(chunk):
            continue
        g = (chunk.groupby(["ид_канала_данных", "бакет"], sort=False)
             [COUNT_COLS[task]].sum())
        for k, v in g.iterrows():
            t = tuple(int(x) for x in v)
            if k in agg:                       # возможны дубли ключей между чанками
                agg[k] = tuple(a + b for a, b in zip(agg[k], t))
            else:
                agg[k] = t
    return agg


def _task_channels(task: str) -> set:
    du = _m("data_utils")
    ref = du.load_ref_channels()
    from app import task_cfg
    return set(ref.loc[ref["тип_датчика"].isin(task_cfg.TASKS[task]["types"]),
                       "ид_канала_данных"])


def _cache_available() -> bool:
    return (config.RAW_DIR / "buckets_2026.parquet").exists()


pytestmark = pytest.mark.skipif(not _cache_available(),
                                reason="нет кэша сырых бакетов (сначала run_demo.py)")

@pytest.mark.parametrize("task", ["wear", "fire", "access", "sensor"])
def test_stream_cache_matches_research_panel_2026(task):
    """Потоковый кэш сервиса == research-панель по счётчикам (канал×бакет), H1-2026."""
    keys = None
    if task not in FULL_CHECK:
        # выборка ключей из сервисного кэша
        all_keys = list(_service_counts(task))
        picked = pd.Series(range(len(all_keys))).sample(
            min(SAMPLE_KEYS, len(all_keys)), random_state=7).tolist()
        keys = {all_keys[i] for i in picked}
    svc = _service_counts(task, keys_only=keys)
    res = _research_counts(task, keys_only=keys)
    assert set(svc) == set(res), (
        f"[{task}] расхождение ключей: svc={len(svc)}, research={len(res)}, "
        f"только в svc={list(set(svc) - set(res))[:5]}, "
        f"только в research={list(set(res) - set(svc))[:5]}")
    diff = {k: (svc[k], res[k]) for k in svc if svc[k] != res[k]}
    assert not diff, f"[{task}] расхождение счётчиков: {list(diff.items())[:5]}"


def test_fire_derived_event_matches_research_2026():
    """Производное событие fire («серьёзных») сервисной панели == research-панели."""
    svc_panel = pd.read_csv(config.PANEL_DIR / "subdaily_panel_fire6h_2026.csv",
                            usecols=["ид_канала_данных", "бакет", "серьёзных"],
                            dtype={"ид_канала_данных": str})
    svc_panel = svc_panel[(svc_panel["бакет"] >= B_MIN) & (svc_panel["бакет"] <= B_MAX)]
    sample = svc_panel.sample(n=min(SAMPLE_KEYS, len(svc_panel)), random_state=11)
    keys = set(zip(sample["ид_канала_данных"], sample["бакет"].astype(int)))
    svc = {(ch, int(b)): int(v) for (ch, b), v in
           zip(zip(sample["ид_канала_данных"], sample["бакет"]),
               sample["серьёзных"])}
    # «серьёзных» из research-панели: читаем колонку на тех же ключах
    fp = _m("features").DATASET / PANEL_COL["fire"]
    res: dict = {}
    for chunk in pd.read_csv(fp, usecols=["ид_канала_данных", "бакет", "серьёзных"],
                             dtype={"ид_канала_данных": str},
                             encoding="utf-8-sig", chunksize=500_000):
        chunk = chunk[(chunk["бакет"] >= B_MIN) & (chunk["бакет"] <= B_MAX)]
        chunk = chunk.set_index(["ид_канала_данных", "бакет"])
        chunk = chunk[chunk.index.isin(keys)].reset_index()
        for (ch, b), v in zip(zip(chunk["ид_канала_данных"],
                                  chunk["бакет"].astype(int)),
                              chunk["серьёзных"]):
            res[(ch, int(b))] = int(v)
    assert set(svc) == set(res)
    assert svc == res, "расхождение «серьёзных» на ключах выборки"