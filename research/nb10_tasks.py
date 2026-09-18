# -*- coding: utf-8 -*-
"""Подход «ноутбук 10» (без TTE) для fire/sensor/access.

Слой 1: бинарный классификатор «событие (старт серии) в 24ч/48ч» - CatBoost.
Слой 2 (справочно): ординальный класс «дней до события» + MAE по нецензурным.
Плюс диагностика «всплесков»: база события в 24ч для ЛЮБОГО события vs старта
серии (как с дымом в 10: 37% -> 11.4%).

Сплит как везде: train <= 2024-12-31, val 2025H1, holdout >= 2025-07-01.
"""
from __future__ import annotations

import argparse
import pathlib

import numpy as np
import pandas as pd

import features as fe
import tte_pipeline as tte
from tte_experiments import pick_threshold, pr_at_horizon

HERE = pathlib.Path(__file__).resolve().parent
MODELS = HERE / "models"

BINS_DAYS = [0.5, 1, 2, 3, 7, 14, 30]
MID = np.array([0.25, 0.75, 1.5, 2.5, 5.0, 10.5, 22.0, 45.0])

# колонка «сырого события» для диагностики всплесков (любое событие в 24ч)
RAW_EVENT_COL = {"fire": "тревог", "sensor": "неисправностей", "access": "тревог"}


def load_subjects(task: str) -> pd.DataFrame:
    return pd.read_parquet(fe.DATASET / f"tte_subjects_{task}.parquet")


def burst_stats(subjects: pd.DataFrame, task: str) -> dict:
    """База «любое событие в 24ч» vs «старт серии в 24ч» (как с дымом в 10)."""
    col = RAW_EVENT_COL[task]
    bucket = subjects["бакет"].to_numpy(np.int64)
    ev = (subjects[col].to_numpy(np.float64) > 0)
    nxt = np.full(len(subjects), np.inf)
    groups = subjects.groupby("ид_канала_данных", sort=False).indices
    for sl in groups.values():
        sl = np.asarray(sl)
        b = bucket[sl]
        eb = b[ev[sl]]
        if not len(eb):
            continue
        j = np.searchsorted(eb, b, side="right")
        ns = np.where(j < len(eb), eb[np.minimum(j, len(eb) - 1)], np.inf)
        nxt[sl] = ns
    raw24 = (nxt - bucket) <= 4
    clean_mask = ~subjects["аномально"].to_numpy()
    raw_base = float(raw24[clean_mask].mean())
    series24 = float(subjects.loc[clean_mask, "цель_серии_24ч"].mean())
    return {"raw_any_24h": raw_base, "series_start_24h": series24,
            "ratio": float(raw_base / max(series24, 1e-9))}
def run_task(task: str, args: argparse.Namespace) -> None:
    subjects = load_subjects(task)
    print(f"[{task}] субъектов: {len(subjects):,}", flush=True)
    bs = burst_stats(subjects, task)
    print(f"  всплески: ЛЮБОЕ событие в 24ч = {bs['raw_any_24h'] * 100:.1f}% | "
          f"старт серии = {bs['series_start_24h'] * 100:.1f}% | "
          f"фактор серий = {bs['ratio']:.1f}x", flush=True)

    train, val, holdout = tte.split_subjects(subjects)
    X_cols = tte.subject_features(train)
    tr = tte.sample_subjects(train, args.n_starts, args.n_fault, args.n_nonfault,
                             seed=args.seed)
    va = tte.sample_subjects(val, args.n_val // 3, args.n_val // 3,
                             args.n_val // 3, seed=args.seed + 1)
    ho = tte.sample_holdout(holdout, args.n_hold, seed=777)

    from catboost import CatBoostClassifier, Pool
    from sklearn.metrics import precision_score as ps, recall_score as rs

    results = []
    for name, y_col in (("24ч", "цель_серии_24ч"), ("48ч", "цель_серии_48ч")):
        Xt = tr.dropna(subset=[y_col]); Xv = va.dropna(subset=[y_col])
        Xh = ho.dropna(subset=[y_col])
        m = CatBoostClassifier(iterations=args.iters, learning_rate=args.lr,
                               depth=args.depth, random_seed=args.seed,
                               task_type="CPU", loss_function="Logloss",
                               eval_metric="Logloss",
                               early_stopping_rounds=100, verbose=50)
        m.fit(Pool(Xt[X_cols], Xt[y_col]), eval_set=Pool(Xv[X_cols], Xv[y_col]))
        yp = m.predict_proba(Xh[X_cols])[:, 1]
        yt = Xh[y_col].astype(int).values
        pr = pr_at_horizon(yt, yp)
        thr = pick_threshold(Xv[y_col].astype(int).values,
                             m.predict_proba(Xv[X_cols])[:, 1], min_precision=0.7)
        hold_p = hold_r = float("nan")
        if np.isfinite(thr[0]):
            yhp = (yp >= thr[0]).astype(int)
            hold_p, hold_r = ps(yt, yhp, zero_division=0), rs(yt, yhp)
        results.append({"горизонт": name, "база": pr["base"],
                        "PR-AUC": pr["pr_auc"], "prec@r>=.5": pr["prec@r>=.5"],
                        "порог(val)": round(thr[0], 2), "hold_pr": round(hold_p, 3),
                        "hold_rec": round(hold_r, 3)})
        print(f"  [{name}] PR-AUC={pr['pr_auc']:.4f} база={pr['base']*100:.1f}% "
              f"thr(val)={thr[0]:.2f} -> hold pr={hold_p:.3f} rec={hold_r:.3f}",
              flush=True)

    # слой 2 (справочно): ординальный класс «дней до события» + MAE по нецензурным
    for dfx in (tr, va, ho):
        dfx["дни_класс"] = np.clip(np.digitize(dfx["дни_до_серии"], BINS_DAYS),
                                   0, len(BINS_DAYS))
        dfx["дни_класс"] = dfx["дни_класс"].fillna(len(BINS_DAYS)).astype(int)
    m2 = CatBoostClassifier(iterations=args.iters, learning_rate=args.lr,
                            depth=args.depth, random_seed=args.seed,
                            loss_function="MultiClass", eval_metric="Accuracy",
                            early_stopping_rounds=100, verbose=0)
    m2.fit(Pool(tr[X_cols], tr["дни_класс"]), eval_set=Pool(va[X_cols], va["дни_класс"]))
    proba = m2.predict_proba(ho[X_cols])
    exp_days = proba @ MID
    obs = ho["дни_до_серии"].notna().values
    err = np.abs(exp_days[obs] - ho["дни_до_серии"].values[obs])
    print(f"  ординальный класс: MAE(нецензурные)={err.mean():.2f} дн | "
          f"медиана|err|={np.median(err):.2f} | цензур={100*(1-obs.mean()):.1f}%",
          flush=True)

    res = pd.DataFrame(results)
    res.insert(0, "задача", task)
    res.to_csv(MODELS / f"nb10_{task}.csv", index=False)
    print(res.round(3).to_string(index=False), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="+", default=["fire", "sensor", "access"])
    ap.add_argument("--n-starts", type=int, default=15_000)
    ap.add_argument("--n-fault", type=int, default=10_000)
    ap.add_argument("--n-nonfault", type=int, default=10_000)
    ap.add_argument("--n-val", type=int, default=6_000)
    ap.add_argument("--n-hold", type=int, default=20_000)
    ap.add_argument("--iters", type=int, default=500)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    for t in a.tasks:
        run_task(t, a)


if __name__ == "__main__":
    main()