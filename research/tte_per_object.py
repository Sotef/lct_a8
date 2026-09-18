# -*- coding: utf-8 -*-
"""Обучение TTE-моделей ПО ОТДЕЛЬНЫМ ОБЪЕКТАМ и сравнение с глобальной моделью.

Логика та же, что в ноутбуке 11 (discrete hazard, person-time, цензура,
holdout >= 2025-07-01), но каждая модель обучается только на строках своего
объекта. Фичи идентичны глобальной модели; для объекта ид_объект_code
константен (бесполезен), остальные признаки (тип, окна, контекст) работают.

Запуск (из research/):
    .venv\\Scripts\\python.exe tte_per_object.py --profile          # статистика по объектам
    .venv\\Scripts\\python.exe tte_per_object.py --n-objects 3      # пилот (3 объекта)
    .venv\\Scripts\\python.exe tte_per_object.py --n-objects 0      # все подходящие
"""
from __future__ import annotations

import argparse
import pathlib
import time

import numpy as np
import pandas as pd

import tte_pipeline as tte
from tte_experiments import build_dataset, pr_at_horizon, predict_survival_discrete, survival_metrics

HERE = pathlib.Path(__file__).resolve().parent
MODELS = HERE / "models"
OBJ_DIR = MODELS / "objects"


def profile_objects(subjects: pd.DataFrame) -> pd.DataFrame:
    """Размеры объектов по сплитам (только для решения о пригодности к обучению)."""
    tr, va, ho = tte.split_subjects(subjects)
    stat = (
        tr.groupby("ид_объект")
          .agg(тр_строк=("бакет", "size"), тр_событий=("event_flag", "sum"))
          .join(va.groupby("ид_объект").agg(вал_строк=("бакет", "size")), how="outer")
          .join(ho.groupby("ид_объект")
                .agg(ho_строк=("бакет", "size"), ho_событий=("event_flag", "sum")), how="outer")
          .fillna(0).astype(int)
          .sort_values("тр_строк", ascending=False)
    )
    return stat


def fit_local(X_tr, y_tr, X_va, y_va, iters, lr, depth, seed):
    """Discrete hazard для одного объекта: ES на его валидации (если она есть)."""
    from catboost import CatBoostClassifier, Pool
    m = CatBoostClassifier(iterations=iters, learning_rate=lr, depth=depth,
                           random_seed=seed, task_type="CPU", loss_function="Logloss",
                           eval_metric="Logloss", early_stopping_rounds=100, verbose=50)
    if X_va is not None and len(X_va) > 0:
        m.fit(Pool(X_tr, y_tr), eval_set=Pool(X_va, y_va))
    else:
        m.fit(Pool(X_tr, y_tr))
    return m


def _pr_auc(y, p):
    try:
        return pr_at_horizon(y, p)["pr_auc"]
    except Exception:
        return float("nan")


def eval_local_vs_global(local_model, global_model, tr_s, ho_o, X_cols):
    """Метрики локальной и глобальной моделей на одних и тех же holdout-субъектах."""

    S_l = predict_survival_discrete(local_model, ho_o, X_cols)
    S_g = predict_survival_discrete(global_model, ho_o, X_cols)
    ho_surv = tte.make_surv_struct(ho_o["event_flag"], ho_o["obs_days"])
    tr_surv = tte.make_surv_struct(tr_s["event_flag"], tr_s["obs_days"])

    y_ho24 = ((ho_o["event_flag"] == 1) & (ho_o["obs_days"] <= 1.01)).to_numpy(int)
    p24_l = 1 - S_l[:, int(round(1.0 * tte.STEPS_PER_DAY)) - 1]
    p24_g = 1 - S_g[:, int(round(1.0 * tte.STEPS_PER_DAY)) - 1]

    out = {"S_l": S_l, "S_g": S_g, "surv_ho": ho_surv, "surv_tr": tr_surv,
           "y_ho24": y_ho24, "p24_l": p24_l, "p24_g": p24_g}
    for tag, S, p24 in (("l", S_l, p24_l), ("g", S_g, p24_g)):
        met = survival_metrics(tr_surv, ho_surv, 1 - S[:, -1], S, tte.EVAL_TIMES)
        out[f"uno_c_{tag}"] = met["uno_c"]
        out[f"auc_{tag}"] = met["mean_auc"]
        out[f"ibs_{tag}"] = met["ibs"]
        out[f"pr24_{tag}"] = _pr_auc(y_ho24, p24)
    return out
def load_global(model_path: pathlib.Path):
    from catboost import CatBoostClassifier
    m = CatBoostClassifier()
    m.load_model(str(model_path))
    return m


def main():
    ap = argparse.ArgumentParser(description="TTE по объектам vs глобальная модель")
    ap.add_argument("--profile", action="store_true", help="только статистика по объектам")
    ap.add_argument("--n-objects", type=int, default=0, help="0 = все подходящие")
    ap.add_argument("--min-train", type=int, default=5000)
    ap.add_argument("--cap", type=int, default=6000, help="макс. train-субъектов на объект")
    ap.add_argument("--cap-val", type=int, default=1500)
    ap.add_argument("--iters", type=int, default=250)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--depth", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--global-model", type=pathlib.Path,
                    default=MODELS / "tte_discrete_hazard.cbm")
    args = ap.parse_args()

    subjects = build_dataset()
    train, val, holdout = tte.split_subjects(subjects)
    stat = profile_objects(subjects)
    if args.profile:
        print("ВСЕГО объектов:", len(stat))
        print(stat.to_string())
        return

    OBJ_DIR.mkdir(exist_ok=True)
    eligible = stat[stat["тр_строк"] >= args.min_train].index.tolist()
    if args.n_objects and args.n_objects > 0:
        eligible = eligible[: args.n_objects]
    no_train = stat[stat["тр_строк"] == 0].index.tolist()
    print(f"[main] объектов-кандидатов: {len(eligible)} "
          f"(без истории до 2025-07: {no_train})")

    X_cols = tte.subject_features(train)
    global_model = load_global(args.global_model)

    rows: list[dict] = []
    per_obj = []          # метаданные + предсказания для объединённой оценки
    for obj in eligible:
        t0 = time.time()
        tr_o = train[train["ид_объект"] == obj]
        va_o = val[val["ид_объект"] == obj]
        ho_o = holdout[holdout["ид_объект"] == obj]

        tr_s = tte.sample_subjects(tr_o, args.cap // 3, args.cap // 3,
                                   args.cap // 3, seed=args.seed) if len(tr_o) > args.cap else tr_o
        va_s = (tte.sample_subjects(va_o, args.cap_val // 3, args.cap_val // 3,
                                    args.cap_val // 3, seed=args.seed + 1)
                if len(va_o) else va_o.iloc[0:0])

        X_tr, y_tr = tte.expand_person_time(tr_s, X_cols, tte.HORIZON_BUCKETS)
        X_va = y_va = None
        if len(va_s):
            X_va, y_va = tte.expand_person_time(va_s, X_cols, tte.HORIZON_BUCKETS)
        local = fit_local(X_tr, y_tr, X_va, y_va, args.iters, args.lr,
                          args.depth, args.seed)
        local.save_model(OBJ_DIR / f"tte_obj_{obj}.cbm")

        r = eval_local_vs_global(local, global_model, tr_s, ho_o, X_cols)
        rows.append({
            "объект": obj, "n_train": len(tr_s), "n_val": len(va_s),
            "n_holdout": len(ho_o), "ho_событий": int(ho_o["event_flag"].sum()),
            "uno_c_лок": r["uno_c_l"], "uno_c_глоб": r["uno_c_g"],
            "auc_лок": r["auc_l"], "auc_глоб": r["auc_g"],
            "ibs_лок": r["ibs_l"], "ibs_глоб": r["ibs_g"],
            "pr24_лок": r["pr24_l"], "pr24_глоб": r["pr24_g"],
        })
        per_obj.append(r)
        print(f"[obj {obj}] n_train={len(tr_s)} n_ho={len(ho_o)} "
              f"Uno-C лок={r['uno_c_l']:.3f}/глоб={r['uno_c_g']:.3f} "
              f"| IBS лок={r['ibs_l']:.3f}/глоб={r['ibs_g']:.3f} "
              f"| PR24 лок={r['pr24_l']:.3f}/глоб={r['pr24_g']:.3f} "
              f"({time.time() - t0:.0f}с)")

    df = pd.DataFrame(rows)
    df.to_csv(MODELS / "per_object_results.csv", index=False, encoding="utf-8-sig")
    print("\n=== Таблица: локальная vs глобальная (по объектам) ===\n")
    print(df.round(3).to_string(index=False))

    # Парное сравнение
    d_uno = df["uno_c_лок"] - df["uno_c_глоб"]
    d_ibs = df["ibs_лок"] - df["ibs_глоб"]
    print("\nПарные дельты (лок - глоб):")
    print(f"  Uno-C: mean={d_uno.mean():+.3f} med={d_uno.median():+.3f} | "
          f"лок лучше в {(d_uno > 0).mean() * 100:.0f}% объектов")
    print(f"  IBS:   mean={d_ibs.mean():+.3f} med={d_ibs.median():+.3f} | "
          f"лок лучше в {(d_ibs < 0).mean() * 100:.0f}% объектов")

    # Объединённая выборка: локальные (по своим объектам) vs глобальная
    surv_ho_uni = np.concatenate([r["surv_ho"] for r in per_obj])
    tr_g = tte.sample_subjects(train, 25_000, 18_000, 18_000, seed=42)
    surv_tr_uni = tte.make_surv_struct(tr_g["event_flag"], tr_g["obs_days"])
    S_l_u = np.vstack([r["S_l"] for r in per_obj])
    S_g_u = np.vstack([r["S_g"] for r in per_obj])
    m_l = survival_metrics(surv_tr_uni, surv_ho_uni, 1 - S_l_u[:, -1], S_l_u, tte.EVAL_TIMES)
    m_g = survival_metrics(surv_tr_uni, surv_ho_uni, 1 - S_g_u[:, -1], S_g_u, tte.EVAL_TIMES)
    print("\n=== ОБЪЕДИНЁННАЯ выборка объектов (holdout) ===")
    print(f"  ЛОКАЛЬНЫЕ (по своим объектам): Uno-C={m_l['uno_c']:.3f} "
          f"AUC={m_l['mean_auc']:.3f} IBS={m_l['ibs']:.3f}")
    print(f"  ГЛОБАЛЬНАЯ:                    Uno-C={m_g['uno_c']:.3f} "
          f"AUC={m_g['mean_auc']:.3f} IBS={m_g['ibs']:.3f}")

    # Итоговый JSON (для ноутбука сравнения и отчётности)
    import json
    params = {k: (str(v) if isinstance(v, pathlib.Path) else v)
              for k, v in vars(args).items()}
    summary = {
        "params": params,
        "rows": df.round(4).to_dict(orient="records"),
        "deltas": {"uno_c_mean": float(d_uno.mean()), "uno_c_med": float(d_uno.median()),
                   "uno_c_share_local_better": float((d_uno > 0).mean()),
                   "ibs_mean": float(d_ibs.mean()), "ibs_med": float(d_ibs.median()),
                   "ibs_share_local_better": float((d_ibs < 0).mean())},
        "union": {
            "local": {"uno_c": float(m_l["uno_c"]), "mean_auc": float(m_l["mean_auc"]),
                      "ibs": float(m_l["ibs"])},
            "global": {"uno_c": float(m_g["uno_c"]), "mean_auc": float(m_g["mean_auc"]),
                       "ibs": float(m_g["ibs"])},
        },
    }
    with open(MODELS / "per_object_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("\n[save] models/per_object_results.csv + per_object_summary.json")


if __name__ == "__main__":
    main()