# -*- coding: utf-8 -*-
"""Параллельная сборка sensor-панели (по годам, для ускорения на многоядерной машине).

Эквивалент `rebuild_task_panels.build_sensor`, но чтение журналов по годам
идёт в N параллельных процессах (_aggregate_bucket_year — независим по годам).
Итог — тот же `dataset/subdaily_panel_sensor6h.csv` с колонками
`пр_разрывов` / `неисправн_дым` и окнами, кэш субъектов инвалидируется.

Запуск (из research/):
    .venv\\Scripts\\python.exe _parallel_build_sensor.py
"""
from __future__ import annotations

import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

import features as fe
import rebuild_task_panels as rp

TASKS_SENSOR = rp.TASKS_SENSOR
YEAR_PARTS = pathlib.Path(fe.DATASET) / "_bucket_year_parts"
OUT_CSV = fe.DATASET / "subdaily_panel_sensor6h.csv"


def _extra_spec():
    ref_ch = fe.du.load_ref_channels()[["ид_канала_данных", "тип_датчика"]]
    all_ch = _ch_of(ref_ch, TASKS_SENSOR)
    extra = {
        "пр_разрывов": {"kind": "value_by_type", "count_channels": True,
                        "channels": all_ch, "values": fe.OPEN_LOOP_VALUES},
        "неисправн_дым": {"kind": "value_by_type", "count_channels": True,
                          "channels": _ch_of(ref_ch, ["Датчик дыма"]),
                          "values": fe.FAULT_STATUSES},
    }
    return extra


def _ch_of(ref: pd.DataFrame, types) -> set:
    return set(ref.loc[ref["тип_датчика"].isin(types), "ид_канала_данных"])


def _year_to_csv(year: str) -> tuple[str, int]:
    """Считает готовый по-годовой bucket-frame и пишет в parquet-кэш."""
    ref_ch = fe.du.load_ref_channels()[["ид_канала_данных", "тип_датчика"]]
    ch_set = _ch_of(ref_ch, TASKS_SENSOR)
    extra = _extra_spec()
    t0 = time.time()
    agg = fe._aggregate_bucket_year(year, ch_set, fe.FAULT_STATUSES,
                                    fe.NOISE_VALUES, extra_cols=extra)
    out = YEAR_PARTS / f"year_{year}.parquet"
    agg.to_parquet(out, index=False)
    return year, len(agg), time.time() - t0


def main() -> None:
    years = list(map(str, range(2019, 2027)))
    YEAR_PARTS.mkdir(exist_ok=True)
    n_workers = min(8, len(years))

    t0 = time.time()
    ok = {}
    if n_workers <= 1:
        for y in years:
            _, n, dt = _year_to_csv(y)
            ok[y] = n
            print(f"  {y}: {n:,} бакето-строк за {dt:.0f}с", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=n_workers) as ex:
            futs = {ex.submit(_year_to_csv, y): y for y in years}
            for f in futs:
                y, n, dt = f.result()
                ok[y] = n
                print(f"  {y}: {n:,} бакето-строк за {dt:.0f}с [{time.time()-t0:.0f}с всего]",
                      flush=True)
    print(f"[parallel] годы готовы за {time.time()-t0:.0f}с", flush=True)

    parts = [pd.read_parquet(YEAR_PARTS / f"year_{y}.parquet") for y in years]
    extra = _extra_spec()
    t1 = time.time()
    df = fe.make_subdaily_panel(
        types=TASKS_SENSOR, recompute=False, out_csv=OUT_CSV,
        extra_cols=extra, precomputed=parts)
    print(f"[panel] {df.shape} за {time.time()-t1:.0f}с", flush=True)

    # аналог rp._save: сортировка + запись + инвалидация кэша субъектов
    df = df.sort_values(["ид_канала_данных", "бакет"]).reset_index(drop=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"[save] panel: {OUT_CSV} ({len(df):,} строк)", flush=True)
    for p in fe.DATASET.glob("tte_subjects_sensor.parquet"):
        p.unlink()
        print(f"[cache] removed: {p.name}", flush=True)
    print("done.", flush=True)


if __name__ == "__main__":
    main()