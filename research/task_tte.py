# -*- coding: utf-8 -*-
"""TTE для остальных задач research (пайплайн = как wear, ноутбук 11).

Задачи:
  --task fire    пожарный риск: событие = серия ТРЕВОГ дыма/пожара;
  --task sensor  отказ датчиков: событие = статус «Неисправен/Обесточен/Отключено»;
  --task access  несанкционированный доступ: событие = серия ОХРАННЫХ тревог.

Один и тот же конвейер: 6ч-панель (`features.make_subdaily_panel`) -> серии ->
правая цензура -> person-time discrete hazard (CatBoost) -> метрики на
holdout >= 2025-07-01 (обучение <= 2024-12-31, внутренняя валидация 2025H1).

Запуск (из research/):
    .venv\\Scripts\\python.exe task_tte.py --task fire --build   # сборка панели
    .venv\\Scripts\\python.exe task_tte.py --task fire           # обучение/оценка
    .venv\\Scripts\\python.exe task_tte.py --task sensor --build
"""
from __future__ import annotations

import argparse
import pathlib
import time

import numpy as np
import pandas as pd

import features as fe
import tte_pipeline as tte
from tte_experiments import (baseline_survival_by_type, calibration_oe,
                             fit_discrete_hazard, pick_threshold, pr_at_horizon,
                             predict_survival_discrete, survival_metrics)

HERE = pathlib.Path(__file__).resolve().parent
MODELS = HERE / "models"

# --- Конфигурация задач ----------------------------------------------------
# event_col: по какой колонке панели определять событие-серию.
TASKS = {
    "fire": {
        "types": ["Датчик дыма", "Тепловой датчик", "Ручной извещатель",
                  "Датчик температуры"],
        "csv": "subdaily_panel_fire6h.csv",
        # НОВОЕ событие (итерация 3): «серьёзная тревога» = подтверждённое
        # задымление (>=2 дымовых канала объекта за 6ч бакет) ИЛИ срабатывание
        # ручного извещателя («Рычаг сдернут»). Колонка собирается
        # rebuild_task_panels.py; раньше событием была серия ЛЮБЫХ тревог дыма
        # (в основном спорадические/ложные -> Uno-C~0.51).
        "event_col": "серьёзных",
        "desc": "пожарный риск: серьёзная тревога (подтв. дым >=2 ИПР / ручной)",
    },
    "sensor": {
        "types": ["Датчик дыма", "Датчик движения", "Датчик температуры",
                  "Газовый датчик", "КД Дверь", "КД АВ", "КД Люк",
                  "Тепловой датчик", "Стекло", "Датчик затопления"],
        "csv": "subdaily_panel_sensor6h.csv",
        "event_col": "неисправностей",  # статус неисправности датчика
        "desc": "отказ датчика",
    },
    "access": {
        "types": ["КД Дверь", "Датчик движения", "КД АВ", "КД Люк",
                  "Стекло", "9-секционный люк"],
        "csv": "subdaily_panel_access6h.csv",
        "event_col": "тревог",       # серия охранных тревог
        "desc": "несанкционированный доступ",
    },
}


def build_task_panel(task: str, recompute: bool = True) -> pd.DataFrame:
    """Сборка 6ч-панели нужного типа (через features.make_subdaily_panel)."""
    cfg = TASKS[task]
    out = fe.DATASET / cfg["csv"]
    if not recompute and out.exists():
        return pd.read_csv(out, dtype={"ид_канала_данных": str, "ид_объект": str})
    t0 = time.time()
    panel = fe.make_subdaily_panel(types=cfg["types"], recompute=True, out_csv=out)
    print(f"[build {task}] {panel.shape} за {time.time() - t0:.0f}с")
    return panel


def prepare_subjects(panel: pd.DataFrame, task: str,
                     cfg: dict, cache: str | None = None) -> pd.DataFrame:
    """Субъекты с цензурой (переиспользует tte_pipeline, событие - серия event_col)."""
    fp = None if cache is None else fe.DATASET / cache
    if fp is not None and fp.exists():
        return pd.read_parquet(fp)
    panel = tte.refit_z_train_only(panel)
    panel = tte.add_series_context(panel, event_col=cfg["event_col"])
    subjects = tte.add_tte_labels(panel)
    subjects["ид_объект_code"] = subjects["ид_объект"].astype("category").cat.codes
    subjects["тип_датчика_code"] = subjects["тип_датчика"].astype("category").cat.codes
    subjects = subjects.sort_values(["ид_канала_данных", "бакет"]).reset_index(drop=True)
    if fp is not None:
        subjects.to_parquet(fp, index=False)
        print(f"[cache] -> {fp.name} ({len(subjects):,} строк)")
    return subjects
def run(task: str, args: argparse.Namespace) -> None:
    cfg = TASKS[task]
    if getattr(args, "event_col", None):
        cfg = {**cfg, "event_col": args.event_col}
    suf = "" if cfg["event_col"] == TASKS[task]["event_col"] \
        else f"_{cfg['event_col']}"
    panel = build_task_panel(task, recompute=args.build)
    cache = f"tte_subjects_{task}.parquet"
    if suf:
        cache = f"tte_subjects_{task}{suf}.parquet"
    subjects = prepare_subjects(panel, task, cfg, cache=cache)

    print(f"[main {task}] субъектов: {subjects.shape[0]:,} | событий в 30д: "
          f"{subjects['event_flag'].mean() * 100:.1f}%")
    train, val, holdout = tte.split_subjects(subjects)
    print(f"[main] split: train={len(train):,} val={len(val):,} "
          f"holdout={len(holdout):,}")

    X_cols = tte.subject_features(train)
    tr = tte.sample_subjects(train, args.n_starts, args.n_fault,
                             args.n_nonfault, seed=args.seed)
    va = tte.sample_subjects(val, args.n_val // 3, args.n_val // 3,
                             args.n_val // 3, seed=args.seed + 1)
    ho = tte.sample_holdout(holdout, args.n_hold, seed=777)
    print(f"[main] выборки: train={len(tr):,} val={len(va):,} holdout={len(ho):,}")

    X_tr, y_tr = tte.expand_person_time(tr, X_cols, tte.HORIZON_BUCKETS)
    X_va, y_va = tte.expand_person_time(va, X_cols, tte.HORIZON_BUCKETS)
    m = fit_discrete_hazard(X_tr, y_tr, X_va, y_va, iters=args.iters,
                            lr=args.lr, depth=args.depth, seed=args.seed,
                            task_type=args.task_type)
    m.save_model(MODELS / f"tte_{task}{suf}_discrete_hazard.cbm")

    surv_tr = tte.make_surv_struct(tr["event_flag"], tr["obs_days"])
    surv_ho = tte.make_surv_struct(ho["event_flag"], ho["obs_days"])
    S_ho = predict_survival_discrete(m, ho, X_cols)
    risk = 1 - S_ho[:, -1]
    met = survival_metrics(surv_tr, surv_ho, risk, S_ho, tte.EVAL_TIMES)

    # порог P(24ч) - только по внутренней валидации
    S_va = predict_survival_discrete(m, va, X_cols)
    y_va24 = ((va["event_flag"] == 1) & (va["obs_days"] <= 1.01)).to_numpy(int)
    p_va24 = 1 - S_va[:, int(round(1.0 * tte.STEPS_PER_DAY)) - 1]
    thr = pick_threshold(y_va24, p_va24, min_precision=0.7)
    y_ho24 = ((ho["event_flag"] == 1) & (ho["obs_days"] <= 1.01)).to_numpy(int)
    p_ho24 = 1 - S_ho[:, int(round(1.0 * tte.STEPS_PER_DAY)) - 1]
    pr24 = pr_at_horizon(y_ho24, p_ho24)
    oe = calibration_oe(S_ho, ho, 30.0)

    # якоря KM/NA по типам каналов
    S_km, S_na = baseline_survival_by_type(
        surv_tr, tr["тип_датчика"].to_numpy(), ho["тип_датчика"].to_numpy(),
        tte.EVAL_TIMES)
    km = survival_metrics(surv_tr, surv_ho, 1 - S_km[:, -1], S_km, tte.EVAL_TIMES)

    hl = ["=" * 60]
    hl.append(f"ЗАДАЧА: {cfg['desc']} (событие = серия по {cfg['event_col']})")
    hl.append(f"holdout >= {tte.HOLDOUT_START.date()}: {len(ho):,} субъектов")
    hl.append(f"Uno-C={met['uno_c']:.3f} | meanAUC={met['mean_auc']:.3f} "
              f"| IBS={met['ibs']:.3f} | KM-якорь: Uno-C={km['uno_c']:.3f} "
              f"IBS={km['ibs']:.3f}")
    hl.append(f"P(24ч): PR-AUC={pr24['pr_auc']:.4f} prec@r>=.5={pr24['prec@r>=.5']:.4f} "
              f"база={pr24['base'] * 100:.1f}% | порог(val)={thr[0]:.2f}")
    txt = "\n".join(hl)
    print("\n" + txt)
    print("\nOCE-калибровка 30д:\n" + oe.round(3).to_string())

    out = ho[["ид_канала_данных", "бакет", "дата", "тип_датчика",
              "event_flag", "obs_days"]].copy()
    out["p24"] = p_ho24
    out["risk30"] = risk
    out["exp_days"] = S_ho.sum(axis=1) / tte.STEPS_PER_DAY
    out.to_parquet(MODELS / f"tte_{task}{suf}_holdout.parquet", index=False)
    (MODELS / f"tte_{task}{suf}_report.txt").write_text(txt, encoding="utf-8")
    print(f"[save] model/preds/report -> models/tte_{task}_*")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, choices=list(TASKS))
    ap.add_argument("--event-col", default=None,
                    help="переопределить столбец-событие (для A/B старого/нового события)")
    ap.add_argument("--build", action="store_true", help="пересобрать панель")
    ap.add_argument("--n-starts", type=int, default=15_000)
    ap.add_argument("--n-fault", type=int, default=10_000)
    ap.add_argument("--n-nonfault", type=int, default=10_000)
    ap.add_argument("--n-val", type=int, default=6_000)
    ap.add_argument("--n-hold", type=int, default=20_000)
    ap.add_argument("--iters", type=int, default=1000)
    ap.add_argument("--lr", type=float, default=0.03)
    ap.add_argument("--depth", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--task-type", type=str, default="CPU", choices=["CPU", "GPU"],
                    help="CPU или GPU для CatBoost (GPU: только iters/lr/depth/l2)")
    ns = ap.parse_args()
    run(ns.task, ns)


if __name__ == "__main__":
    main()