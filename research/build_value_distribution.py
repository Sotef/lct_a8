# -*- coding: utf-8 -*-
"""Разовый агрегат: распределение показаний датчиков по ТИПАМ и ОБЪЕКТАМ.

Считает по журналам СМВУ (ext-journal-*.csv) счётчики значений_датчика:
  - по типам датчиков        -> dataset/value_by_type.csv
  - по объектам              -> dataset/value_by_object.csv
Заодно добавляет семантический тег значения (шум/неисправность/движение/пожар/
числовое/прочее). Чанками по 2 млн строк, только 2 колонки журнала.

Запуск: .venv\\Scripts\\python.exe build_value_distribution.py
"""
from __future__ import annotations

import collections
import time

import pandas as pd

import data_utils as du
import features as fe

NOISE = {"0.00", "0.01", "0.02"}


def semantic(value: str) -> str:
    v = value.strip()
    if v in NOISE:
        return "шум (0.00/0.01/0.02)"
    if v in fe.FAULT_STATUSES:
        return "статус-неисправность"
    if v in ("Обнаружено движение", "Движения нет"):
        return "движение"
    if v in ("Пожар", "Задымление", "Дым", "Нет дыма"):
        return "пожар/задымление"
    if v in ("Открыто", "Закрыто", "Норма", "Нормально", "В норме"):
        return "норма/состояние"
    if du.is_numeric_value(v):
        return "числовое"
    return "прочий текст"


def main() -> None:
    ref = du.load_ref_channels()[["ид_канала_данных", "тип_датчика", "ид_объект"]]
    ref = ref.dropna(subset=["ид_объект", "тип_датчика"])
    ch_to_type = dict(zip(ref["ид_канала_данных"], ref["тип_датчика"]))
    ch_to_obj = dict(zip(ref["ид_канала_данных"], ref["ид_объект"]))

    cnt_ty = collections.Counter()
    cnt_obj = collections.Counter()
    t0 = time.time()
    for fp in du.journal_files():
        for ch in du.read_chunks(fp, cols=["ид_канала_данных", "значение_датчика"],
                                 chunksize=2_000_000):
            m = ch["ид_канала_данных"].isin(ch_to_type)
            if not m.any():
                continue
            g = ch[m]
            types = g["ид_канала_данных"].map(ch_to_type)
            objs = g["ид_канала_данных"].map(ch_to_obj)
            vals = g["значение_датчика"].fillna("<нет>").astype(str).str.strip()
            cnt_ty.update(zip(types, vals))
            cnt_obj.update(zip(objs, vals))
        print(f"  {fp.name}: {sum(cnt_ty.values()):,} | "
              f"{time.time() - t0:.0f}с", flush=True)

    def to_df(cnt) -> pd.DataFrame:
        df = pd.DataFrame(list(cnt.items()), columns=["k", "v"])
        df[["a", "значение"]] = pd.DataFrame(df["k"].tolist(), index=df.index)
        df = df.drop(columns=["k"]).rename(columns={"a": "группа", "v": "n"})
        df["семантика"] = df["значение"].map(semantic)
        return df[["группа", "значение", "семантика", "n"]].sort_values(
            ["группа", "n"], ascending=[True, False]).reset_index(drop=True)

    ty = to_df(cnt_ty).rename(columns={"группа": "тип_датчика"})
    ob = to_df(cnt_obj).rename(columns={"группа": "ид_объект"})
    ty.to_csv(fe.DATASET / "value_by_type.csv", index=False, encoding="utf-8-sig")
    ob.to_csv(fe.DATASET / "value_by_object.csv", index=False, encoding="utf-8-sig")
    print("saved:", fe.DATASET / "value_by_type.csv",
          fe.DATASET / "value_by_object.csv", f"({time.time() - t0:.0f}с)")


if __name__ == "__main__":
    main()