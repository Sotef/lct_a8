# -*- coding: utf-8 -*-
"""Сборка метаданных каналов для плана ТО: возраст оборудования (первая запись).

Возраст = «сейчас» − первая запись с этого датчика за ВСЁ доступное время
(2019…2026). Источник — субъекты обучения research (`dataset/tte_subjects*.parquet`,
колонки `ид_канала_данных, бакет`): это та же 6ч-сетка и тот же справочник каналов,
что использует сервис, и объединение всех задач покрывает 100% каналов сервиса
(проверено: 9766/9766). Реестр оборудования не используем — его не дают.

Результат: `services/data/channel_first_seen.csv`
    ид_канала_данных, first_bucket, first_ts
где first_ts = 1970-01-01 + 6ч * first_bucket (та же 6ч-сетка, что в сервисе).

Запуск (research-venv с pandas/pyarrow; из корня репозитория):
    <research-venv>/Scripts/python.exe services/scripts/build_channel_meta.py
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = pathlib.Path(__file__).resolve().parent          # services/scripts
SERVICE = HERE.parent                                   # services
ROOT = SERVICE.parent                                   # lct_a8
DATASET = ROOT / "research" / "dataset"
SOURCES = ["tte_subjects.parquet", "tte_subjects_fire.parquet",
           "tte_subjects_access.parquet", "tte_subjects_sensor.parquet"]
OUT = SERVICE / "data" / "channel_first_seen.csv"
EPOCH = dt.datetime(1970, 1, 1)


def bucket_ts(bucket: int) -> str:
    return (EPOCH + dt.timedelta(hours=6 * int(bucket))).strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    files = [DATASET / n for n in SOURCES]
    files = [f for f in files if f.exists()]
    if not files:
        print(f"нет файлов tte_subjects*.parquet в {DATASET}", file=sys.stderr)
        return 1
    frames = []
    for f in files:
        df = pd.read_parquet(f, columns=["ид_канала_данных", "бакет"])
        df = df[df["бакет"].notna()]
        print(f"  {f.name}: {len(df):>9} строк, каналов {df['ид_канала_данных'].nunique()}")
        frames.append(df)
    allb = pd.concat(frames, ignore_index=True)
    first = (allb.groupby("ид_канала_данных", as_index=False)["бакет"].min()
             .rename(columns={"бакет": "first_bucket"}))
    first["first_bucket"] = first["first_bucket"].astype("int64")
    first["ид_канала_данных"] = first["ид_канала_данных"].astype(str)
    first["first_ts"] = first["first_bucket"].map(bucket_ts)
    first = first.sort_values("first_bucket")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    first.to_csv(OUT, index=False, encoding="utf-8-sig")
    years = first["first_ts"].str[:4].value_counts().sort_index()
    print(f"\nканалов всего: {len(first)}  ->  {OUT}")
    print("первая запись по годам:")
    for y, n in years.items():
        print(f"  {y}: {n}")
    # возраст каналов на 2026-01-01 (для контроля)
    t0 = dt.datetime(2026, 1, 1)
    age = first["first_ts"].map(lambda s: (t0 - dt.datetime.fromisoformat(s)).days / 365.25)
    print(f"возраст на 2026-01-01: медиана {age.median():.2f} г, "
          f"p10 {age.quantile(.1):.2f}, p90 {age.quantile(.9):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
