# -*- coding: utf-8 -*-
"""Пересборка 6ч-панелей fire/access/sensor с семантическими колонками.

Итерация 3 (решение §8 PLAN_OTHER_TASKS.md): вместо «сырой» тревоги — счётчики
по смыслу значений журнала и подтверждению на объекте:

  fire (событие переопределено):
    - задымлений      — счётчик «Обнаружен дым/Дым/...» по дымовым каналам;
    - серьёзн_ручной  — счётчик «Рычаг сдернут» по ручным извещателям;
    - тревог_дым / тревог_тепло — тревоги по типам;
    - каналов_задымлений_об_б — число дымовых каналов объекта, увидевших дым;
    - задым_подтв_об_б = (каналов_задымлений_об_б >= 2) — подтверждённая серия;
    - серьёзных = подтверждённое задымление ИЛИ ручной извещатель — НОВЫЙ
      event_col для TTE fire (вместо «тревог»).

  access (features, событие прежнее):
    - тревог_дверь / тревог_движение по типам;
    - дверь_движение_об_б = «открытие+движение в одном 6ч бакете» (sequential).

  sensor (features):
    - пр_разрывов — «Не замкнут» (признак деградации/обрыва шлейфа);
    - неисправн_дым — неисправности только по дымовым каналам.

После сборки удаляет старые кэши субъектов (tte_subjects_*.parquet), чтобы
train/val/holdout пересчитались по новой панели.

Запуск (из research/, читает журналы, ~5-15 мин на задачу):
    .venv\\Scripts\\python.exe rebuild_task_panels.py --tasks fire
    .venv\\Scripts\\python.exe rebuild_task_panels.py            # все три
"""
from __future__ import annotations

import argparse
import pathlib

import numpy as np
import pandas as pd

import features as fe
import tte_pipeline as tte

TASKS_FIRE = ["Датчик дыма", "Тепловой датчик", "Ручной извещатель",
              "Датчик температуры"]
TASKS_ACCESS = ["КД Дверь", "Датчик движения", "КД АВ", "КД Люк", "Стекло",
                "9-секционный люк"]
TASKS_SENSOR = ["Датчик дыма", "Датчик движения", "Датчик температуры",
                "Газовый датчик", "КД Дверь", "КД АВ", "КД Люк",
                "Тепловой датчик", "Стекло", "Датчик затопления"]


def _ch_of(ref: pd.DataFrame, types) -> set:
    """Множество ид_каналов заданных типов из реестра (без строковой миграции)."""
    return set(ref.loc[ref["тип_датчика"].isin(types), "ид_канала_данных"])


def build_fire() -> None:
    ref_ch = fe.du.load_ref_channels()[["ид_канала_данных", "тип_датчика"]]
    smoke_ch = _ch_of(ref_ch, ["Датчик дыма"])
    manual_ch = _ch_of(ref_ch, ["Ручной извещатель"])
    extra = {
        "задымлений": {"kind": "value_by_type", "count_channels": True,
                       "channels": smoke_ch, "values": fe.SMOKE_ALARM_VALUES},
        "серьёзн_ручной": {"kind": "value_by_type", "count_channels": True,
                           "channels": manual_ch, "values": fe.MANUAL_ALARM_VALUES},
        "тревог_дым": {"kind": "alarm_by_type", "count_channels": True,
                       "channels": smoke_ch},
        "тревог_тепло": {"kind": "alarm_by_type",
                         "channels": _ch_of(ref_ch, ["Тепловой датчик"])},
    }
    df = fe.make_subdaily_panel(
        types=TASKS_FIRE, recompute=True,
        out_csv=fe.DATASET / "subdaily_panel_fire6h.csv", extra_cols=extra)
    # подтверждённая серия задымления: >= 2 дымовых канала объекта за бакет
    df["задым_подтв_об_б"] = (df["каналов_задымлений_об_б"].to_numpy() >= 2).astype(np.int8)
    df = fe._add_bucket_windows(df, ["задым_подтв_об_б"], windows=fe.BUCKET_WINDOWS,
                                group_col="ид_объект")
    # НОВОЕ событие fire: подтверждённое задымление ИЛИ ручной извещатель
    df["серьёзных"] = (((df["задымлений"].to_numpy() > 0)
                        & (df["задым_подтв_об_б"].to_numpy() == 1))
                       | (df["серьёзн_ручной"].to_numpy() > 0)).astype(np.int8)
    df = fe._add_bucket_windows(df, ["серьёзных"], windows=fe.BUCKET_WINDOWS)
    _save(df, "fire")


def build_access() -> None:
    ref_ch = fe.du.load_ref_channels()[["ид_канала_данных", "тип_датчика"]]
    extra = {
        "тревог_дверь": {"kind": "alarm_by_type", "count_channels": True,
                         "channels": _ch_of(ref_ch, ["КД Дверь"])},
        "тревог_движение": {"kind": "alarm_by_type", "count_channels": True,
                            "channels": _ch_of(ref_ch, ["Датчик движения"])},
    }
    df = fe.make_subdaily_panel(
        types=TASKS_ACCESS, recompute=True,
        out_csv=fe.DATASET / "subdaily_panel_access6h.csv", extra_cols=extra)
    # sequential-паттерн «дверь открыта + сработал объёмник в том же бакете»
    df["дверь_движение_об_б"] = (
        (df["каналов_тревог_дверь_об_б"].to_numpy() > 0)
        & (df["каналов_тревог_движение_об_б"].to_numpy() > 0)).astype(np.int8)
    df = fe._add_bucket_windows(df, ["дверь_движение_об_б"],
                                windows=fe.BUCKET_WINDOWS, group_col="ид_объект")
    _save(df, "access")


def build_sensor() -> None:
    ref_ch = fe.du.load_ref_channels()[["ид_канала_данных", "тип_датчика"]]
    all_ch = _ch_of(ref_ch, TASKS_SENSOR)
    extra = {
        "пр_разрывов": {"kind": "value_by_type", "count_channels": True,
                        "channels": all_ch, "values": fe.OPEN_LOOP_VALUES},
        "неисправн_дым": {"kind": "value_by_type", "count_channels": True,
                          "channels": _ch_of(ref_ch, ["Датчик дыма"]),
                          "values": fe.FAULT_STATUSES},
    }
    df = fe.make_subdaily_panel(
        types=TASKS_SENSOR, recompute=True,
        out_csv=fe.DATASET / "subdaily_panel_sensor6h.csv", extra_cols=extra)
    _save(df, "sensor")


def _save(df: pd.DataFrame, task: str) -> None:
    fp = fe.DATASET / f"subdaily_panel_{task}6h.csv"
    df = df.sort_values(["ид_канала_данных", "бакет"]).reset_index(drop=True)
    df.to_csv(fp, index=False, encoding="utf-8-sig")
    print(f"[{task}] panel saved: {fp.name}, rows={len(df):,}", flush=True)
    # инвалидируем кэши субъектов и классические результаты
    for p in fe.DATASET.glob(f"tte_subjects_{task}.parquet"):
        p.unlink()
        print(f"[{task}] cache removed: {p.name}")
    for p in (fe.DATASET.parent / "models").glob(f"nb10_{task}.csv"):
        p.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="+", default=["fire", "access", "sensor"],
                    choices=["fire", "access", "sensor"])
    a = ap.parse_args()
    builders = {"fire": build_fire, "access": build_access, "sensor": build_sensor}
    for t in a.tasks:
        builders[t]()
    print("done.")


if __name__ == "__main__":
    main()