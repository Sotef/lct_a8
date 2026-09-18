# -*- coding: utf-8 -*-
"""Аномалий-детекция для «Пожарного риска» (без размеченных пожаров).

Идея: агрегируем тревоги дыма до уровня (ОБЪЕКТ x ДЕНЬ), строим признаки
(rolling 7д, std, число каналов, сезонность), учим «норму» ТОЛЬКО на чистом
обучающем окне (<=2024, вне кампаний), затем скорим ИЗВЕСТНЫЕ аномальные
периоды как прокси «ненормальной активности»:
  - кампания проверок ИПР 2021W17-W23 (массовые ложные сработки);
  - локальный всплеск 2026W23 (holdout).
Оценка: recall кампании в топ-X% аномальных дней + доля campagne в топе.
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

import data_utils as du
import features as fe
import tte_pipeline as tte

HERE = pathlib.Path(__file__).resolve().parent
MODELS = HERE / "models"

CAMPAIGN_2021 = set(range(202116, 202124))
CAMPAIGN_2026 = {202623}


def load_fire_subjects():
    return pd.read_parquet(fe.DATASET / "tte_subjects_fire.parquet")


def build_object_days(subjects: pd.DataFrame) -> pd.DataFrame:
    """(объект, день) -> число тревог, число каналов, сезонность."""
    d = subjects.copy()
    d["дата"] = pd.to_datetime(d["дата"])
    d["год_неделя"] = d["год_неделя"].astype(int)
    g = (d.groupby(["ид_объект", "дата"])
           .agg(тревог=("тревог", "sum"),
                каналов=("тревог", lambda s: (s > 0).sum()),
                год_неделя=("год_неделя", "first")).reset_index())
    # rolling-норма ТОЛЬКО по прошлому (shift, чтобы не подглядывать в текущий день)
    g = g.sort_values(["ид_объект", "дата"]).reset_index(drop=True)
    g["тревог7"] = g.groupby("ид_объект")["тревог"].transform(
        lambda s: s.shift(1).rolling(7, min_periods=3).mean())
    g["тревог7_std"] = g.groupby("ид_объект")["тревог"].transform(
        lambda s: s.shift(1).rolling(7, min_periods=3).std())
    g["день_недели"] = g["дата"].dt.dayofweek
    g["месяц"] = g["дата"].dt.month
    g["извест_аномалия"] = (g["год_неделя"].isin(CAMPAIGN_2021)
                            | g["год_неделя"].isin(CAMPAIGN_2026)).astype(int)
    g["аномально_неделя"] = g["год_неделя"].map(du.week_is_campaign).astype(int)
    return g


def main() -> None:
    sub = load_fire_subjects()
    g = build_object_days(sub)
    print("объект-дней:", len(g), "| известных аномальных недель:",
          int(g["извест_аномалия"].sum()))

    dt = g["дата"]
    train_mask = (dt <= tte.TRAIN_END) & (g["аномально_неделя"] == 0)
    # обучаем "норму" только на чистом окне
    X_train = g.loc[train_mask, ["тревог", "тревог7", "тревог7_std",
                                "день_недели", "месяц"]].fillna(0)
    X_all = g[["тревог", "тревог7", "тревог7_std", "день_недели", "месяц"]].fillna(0)

    from sklearn.ensemble import IsolationForest
    iso = IsolationForest(contamination=0.02, random_state=42, n_jobs=-1)
    iso.fit(X_train)
    g["iso_anomaly"] = iso.predict(X_all)  # -1 = аномалия
    g["iso_score"] = -iso.score_samples(X_all)

    # робастный z по прошлому (медиана/MAD)
    def _mad(v):
        med = float(np.median(v))
        return float(np.median(np.abs(v - med))) if v.size else 0.0
    g["z7"] = g.groupby("ид_объект")["тревог"].transform(
        lambda s: s.shift(1).rolling(7, min_periods=3).median())
    g["mad7"] = g.groupby("ид_объект")["тревог"].transform(
        lambda s: s.shift(1).rolling(7, min_periods=3).apply(_mad, raw=True))
    g["robust_z"] = (g["тревог"] - g["тревог7"]) / (g["mad7"] + 1e-6)
    g["z_flag"] = (g["robust_z"] > 6).astype(int)

    rows = []
    for name, flag in (("isolation_forest", g["iso_anomaly"] == -1),
                      ("robust_z>6", g["z_flag"] == 1)):
        n_flag = int(flag.sum())
        in_camp = int((flag & (g["извест_аномалия"] == 1)).sum())
        camp_days = int(g["извест_аномалия"].sum())
        rows.append({"детектор": name, "отмечено_дней": n_flag,
                     "из_них_известн.аномал.": in_camp,
                     "точность_по_известн.": round(in_camp / max(n_flag, 1), 3),
                     "охват_известн.": round(in_camp / max(camp_days, 1), 3)})
        print(name, rows[-1], flush=True)

    # топ по iso_score
    top = g.nlargest(int(0.02 * len(g)), "iso_score")
    print("топ-2% по iso_score: дни в известных аном. неделях:",
          int(top["извест_аномалия"].sum()), "/", len(top), flush=True)

    pd.DataFrame(rows).to_csv(MODELS / "fire_anomaly_summary.csv", index=False)
    g.to_parquet(MODELS / "fire_anomaly_object_days.parquet", index=False)
    print("[save] models/fire_anomaly_*", flush=True)


if __name__ == "__main__":
    main()