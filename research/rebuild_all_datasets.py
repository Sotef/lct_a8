# -*- coding: utf-8 -*-
"""Пересборка ВСЕХ датасетов из исходных .7z (воспроизводимость нового окружения).

Порядок (шаг пропускается, если артефакт уже есть; `--force` пересчитает):
  0. распаковка .7z  -> dataset/extracted/ext-journal-{год}.csv
  1. 6ч-агрегаты WEAR -> dataset/_buckets_raw/_buckets_raw_{год}.csv
  2. 6ч-панель wear   -> dataset/subdaily_panel_wear_6h.csv
  3. суточный панель WEAR -> daily_panel_Состояние_насоса_....csv (для notebook 08)
  4. объектный контекст -> dataset/daily_panel_object_context.csv
  5. 6ч-панели задач fire/sensor/access -> dataset/subdaily_panel_{task}6h.csv
  6. субъекты TTE (parquet): wear, fire, sensor, access
  7. (--values) распределения значений -> value_by_type.csv, value_by_object.csv

Запуск (из research/):
  .venv\\Scripts\\python.exe rebuild_all_datasets.py --check
  .venv\\Scripts\\python.exe rebuild_all_datasets.py --all
  .venv\\Scripts\\python.exe rebuild_all_datasets.py --all --values --force
"""
from __future__ import annotations

import argparse
import pathlib
import time

import data_utils as du
import features as fe
import build_value_distribution as bvd
import task_tte

D = du.find_dataset_dir()
YEARS = list(map(str, range(2019, 2027)))
TASKS = ["fire", "sensor", "access"]

ARTIFACTS = [
    (0, "распаковка журналов", [D / "extracted" / f"ext-journal-{y}.csv" for y in YEARS],
     "~15-25 мин"),
    (1, "6ч-агрегаты WEAR (по годам)",
     [D / "_buckets_raw" / f"_buckets_raw_{y}.csv" for y in YEARS], "~10 мин"),
    (2, "6ч-панель wear", [D / "subdaily_panel_wear_6h.csv"], "~2 мин"),
    (3, "суточный панель WEAR",
     [D / "daily_panel_Состояние_насоса_Состояние_вентилятора_Состояние_фазы.csv"], "~10 мин"),
    (4, "объектный контекст", [D / "daily_panel_object_context.csv"], "~15 мин"),
    (5, "6ч-панели задач (fire/sensor/access)",
     [D / f"subdaily_panel_{t}6h.csv" for t in TASKS], "~25 мин"),
    (6, "субъекты TTE (parquet)",
     [D / "tte_subjects.parquet"] + [D / f"tte_subjects_{t}.parquet" for t in TASKS], "~5 мин"),
    (7, "распределения значений (--values)",
     [D / "value_by_type.csv", D / "value_by_object.csv"], "~8 мин"),
]


def report() -> None:
    print(f"dataset: {D}")
    print(f"{'артефакт':<48}{'файлов':>8}{'размер, МБ':>12}")
    total = 0.0
    for _, name, files, _ in ARTIFACTS:
        present = [f for f in files if f.exists()]
        size = sum(f.stat().st_size for f in present) / 1e6
        total += size
        print(f"{name:<48}{len(present):>5}/{len(files):<4}{size:>12,.1f}")
    print(f"ИТОГО (существующие артефакты): {total:,.1f} МБ")
def unpack() -> None:
    import py7zr
    ex_dir = D / "extracted"
    ex_dir.mkdir(exist_ok=True)
    for y in YEARS:
        a = D / f"ext-journal-{y}.7z"
        out = ex_dir / f"ext-journal-{y}.csv"
        if out.exists():
            print(f"  {y}: есть, skip"); continue
        if not a.exists():
            print(f"  {y}: НЕТ архива {a.name} — пропускаем"); continue
        t0 = time.time()
        with py7zr.SevenZipFile(a, "r") as z:
            z.extractall(path=ex_dir)
        print(f"  {y}: {out.stat().st_size / 1e6:,.0f} МБ за {time.time() - t0:.0f}с")


def build_bucket_raw() -> None:
    rawdir = D / "_buckets_raw"
    rawdir.mkdir(exist_ok=True)
    ref = du.load_ref_channels()[["ид_канала_данных", "тип_датчика", "ид_объект"]].dropna(
        subset=["ид_объект"])
    ch_set = set(ref.loc[ref["тип_датчика"].isin(fe.WEAR_TYPES), "ид_канала_данных"])
    for y in YEARS:
        out = rawdir / f"_buckets_raw_{y}.csv"
        if out.exists():
            print(f"  {y}: есть, skip"); continue
        agg = fe._aggregate_bucket_year(y, ch_set, fe.FAULT_STATUSES, fe.NOISE_VALUES)
        agg.to_csv(out, index=False, encoding="utf-8-sig")
        print(f"  {y}: {len(agg):,}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="выполнить все шаги 0..6")
    ap.add_argument("--check", action="store_true", help="только статус артефактов")
    ap.add_argument("--values", action="store_true", help="+ шаг 7 (распределения значений)")
    ap.add_argument("--force", action="store_true", help="пересчитывать даже если файл есть")
    a = ap.parse_args()

    report()
    if not a.all:
        return

    print("\n[0] распаковка .7z")
    unpack()

    print("\n[1] 6ч-агрегаты WEAR")
    build_bucket_raw()

    print("\n[2] 6ч-панель wear")
    if a.force or not (D / "subdaily_panel_wear_6h.csv").exists():
        fe.make_subdaily_panel(types=fe.WEAR_TYPES, recompute=a.force)
    else:
        print("  есть, skip")

    print("\n[3] суточный панель WEAR (для notebook 08)")
    fe.make_daily_panel(types=fe.WEAR_TYPES, recompute=a.force)

    print("\n[4] объектный контекст")
    fe.make_object_panel(recompute=a.force)

    print("\n[5] 6ч-панели fire/sensor/access")
    for t in TASKS:
        out = D / task_tte.TASKS[t]["csv"]
        if a.force or not out.exists():
            task_tte.build_task_panel(t, recompute=True)
        else:
            print(f"  {t}: есть, skip")

    print("\n[6] субъекты TTE (parquet)")
    if a.force or not (D / "tte_subjects.parquet").exists():
        from tte_experiments import build_dataset as bd_wear
        bd_wear()
    else:
        print("  wear: есть, skip")
    import pandas as pd
    for t in TASKS:
        out = D / f"tte_subjects_{t}.parquet"
        if a.force or not out.exists():
            panel = pd.read_csv(D / task_tte.TASKS[t]["csv"],
                                dtype={"ид_канала_данных": str, "ид_объект": str})
            task_tte.prepare_subjects(panel, t, cache=f"tte_subjects_{t}.parquet")
        else:
            print(f"  {t}: есть, skip")

    if a.values:
        print("\n[7] распределения значений")
        bvd.main()
    else:
        print("\n(шаг 7 пропущен; добавьте --values)")

    print("\nГотово. Артефакты:")
    report()


if __name__ == "__main__":
    main()