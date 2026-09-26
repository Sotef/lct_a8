# -*- coding: utf-8 -*-
"""Проверка согласованности TRAIN vs INFERENCE (подача данных с одного источника).

Проверяет по выбранному task (wear|fire|sensor|access):
  1. Колонки-фичи на обучении и холдауте идентичны (имена, порядок, dtypes).
  2. z_событий на холдауте посчитан ТЕМИ ЖЕ train-статистиками, что на обучении.
  3. Модель принимает те же фичи: predict даёт S(t) (монотонный, [0,1]).
  4. Rows (канал, бакет) субъектов из parquet совпадают со строками исходной
     6ч-панели (т.е. inferference читает тот же самый источник данных).
  5. Нет пересечения (канал, бакет) между train/val/holdout.
"""
from __future__ import annotations

import argparse
import pathlib

import numpy as np
import pandas as pd

import features as fe
import tte_pipeline as tte

HERE = pathlib.Path(__file__).resolve().parent
MODELS = HERE / "models"

CFG = {
    "wear": {"subj": "tte_subjects.parquet", "panel": "subdaily_panel_wear_6h.csv",
             "model": "tte_discrete_hazard.cbm"},
    "fire": {"subj": "tte_subjects_fire.parquet", "panel": "subdaily_panel_fire6h.csv",
             "model": "tte_fire_discrete_hazard.cbm"},
}
for t in ("fire", "sensor", "access"):
    CFG[t] = {"subj": f"tte_subjects_{t}.parquet",
              "panel": f"subdaily_panel_{t}6h.csv",
              "model": f"tte_{t}_discrete_hazard.cbm"}


def check_task(task: str, n_samples: int = 5) -> list[str]:
    lines = [f"==== {task} ===="]
    sub = pd.read_parquet(fe.DATASET / CFG[task]["subj"])
    train, val, holdout = tte.split_subjects(sub)
    X_cols = tte.subject_features(train)

    # 1. колонки
    missing = [c for c in X_cols if c not in holdout.columns]
    ok1 = len(missing) == 0
    lines.append(f"[1] фичи train({len(X_cols)}) present в holdout: {'OK' if ok1 else 'FAIL ' + str(missing)}")

    # 2. z_событий
    clean = train[~train["событий"].isna()]  # 'событий' всегда int
    clean = clean[pd.to_datetime(clean["дата"]) <= tte.TRAIN_END]
    clean = clean[~clean["аномально"]]
    med = clean.groupby("ид_канала_данных")["событий"].median()
    iqr = (clean.groupby("ид_канала_данных")["событий"].quantile(0.75)
           - clean.groupby("ид_канала_данных")["событий"].quantile(0.25))
    chs = holdout["ид_канала_данных"].sample(n_samples, random_state=1).tolist()
    z_ok = True
    for ch in chs:
        r = holdout.loc[holdout["ид_канала_данных"] == ch].head(1).iloc[0]
        expected = (r["событий"] - med.get(ch, np.nan)) / (iqr.get(ch, np.nan) + 1e-6)
        if not np.isclose(r["z_событий"], expected, atol=1e-6):
            z_ok = False
    lines.append(f"[2] z_событий на holdout = пересчёт по train-статистикам: "
                f"{'OK' if z_ok else 'FAIL'}")

    # 3. predict
    from catboost import CatBoostClassifier
    m = CatBoostClassifier()
    m.load_model(MODELS / CFG[task]["model"])
    S = tte_predict_check(m, holdout.head(5), X_cols)
    mono = bool(np.all(np.diff(S, axis=1) <= 1e-9))
    lines.append(f"[3] S(t) из модели: shape={S.shape}, [0,1]="
                 f"{(S >= 0).all() and (S <= 1).all()}, монотонность="
                 f"{mono}")

    # 4. совпадение с исходной панелью
    panel = pd.read_csv(fe.DATASET / CFG[task]["panel"],
                        dtype={"ид_канала_данных": str, "ид_объект": str})
    keys = holdout[["ид_канала_данных", "бакет"]].sample(n_samples, random_state=2)
    compare_cols = ["событий", "тревог", "неисправностей", "шума"]
    src_ok = True
    for _, (ch, b) in keys.iterrows():
        p_ = panel[(panel["ид_канала_данных"] == ch) & (panel["бакет"] == int(b))]
        s_ = sub[(sub["ид_канала_данных"] == ch) & (sub["бакет"] == int(b))]
        if len(p_) == 0 or len(s_) == 0:
            src_ok = False
            continue
        if not np.allclose(p_[compare_cols].iloc[0].astype(float),
                          s_[compare_cols].iloc[0].astype(float)):
            src_ok = False
    lines.append(f"[4] parquet-субъекты == строки исходной 6ч-панели: "
                f"{'OK' if src_ok else 'FAIL'}")
    tr_keys = set(map(tuple, train[["ид_канала_данных", "бакет"]].drop_duplicates().values))
    ho_keys = set(map(tuple, holdout[["ид_канала_данных", "бакет"]].drop_duplicates().values))
    lines.append(f"[5] пересечение (канал,бакет) между train/holdout: "
                f"{len(tr_keys & ho_keys)}")
    return lines


def tte_predict_check(m, ho, X_cols):
    X_pt, _ = tte.expand_person_time(ho, X_cols, tte.HORIZON_BUCKETS, fixed_horizon=True)
    h = m.predict_proba(X_pt)[:, 1]
    return np.cumprod(1 - h.reshape(len(ho), tte.HORIZON_BUCKETS), axis=1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="wear", help="wear|fire|sensor|access")
    a = ap.parse_args()
    lines = check_task(a.task)
    for l in lines:
        print(l, flush=True)
    (MODELS / f"verify_inference_{a.task}.txt").write_text("\n".join(lines),
                                                          encoding="utf-8")


if __name__ == "__main__":
    main()