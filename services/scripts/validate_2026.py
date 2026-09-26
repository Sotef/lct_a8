# -*- coding: utf-8 -*-
"""Валидация моделей на ПОТОКОВЫХ данных H1-2026 (не участвовали в обучении).

Источник — сервисный потоковый кэш (адаптер журнала ext-journal-2026.csv):
субъекты собираются тем же пайплайном, что и в проде (feature_pipeline), затем
модель считает p24/risk30, и метрики сравниваются с фактическими событиями
в 24ч (метки берутся из данных 2026 — это offline-валидация, не утечка в прод).

Запуск:
    services\\.venv\\Scripts\\python.exe scripts\\validate_2026.py            # все задачи
    services\\.venv\\Scripts\\python.exe scripts\\validate_2026.py --tasks wear fire --sample 10000
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.research_bridge import module as _m  # noqa: E402
from app.services import feature_pipeline as fp  # noqa: E402
from app.services import inference as inf  # noqa: E402
from app.services import ml_registry  # noqa: E402

REPORT = pathlib.Path(__file__).resolve().parent.parent / "data" / "validate_2026_report.txt"


def _y24(subjects: pd.DataFrame) -> np.ndarray:
    """Метка «событие в 24ч» (как в research: event_flag & obs_days <= 1.01)."""
    return ((subjects["event_flag"] == 1) & (subjects["obs_days"] <= 1.01)) \
        .to_numpy().astype(int)


def _pr_auc(y: np.ndarray, p: np.ndarray) -> float:
    """Average Precision (PR-AUC) без sklearn (venv не тянет scikit-learn)."""
    if not y.sum():
        return float("nan")
    order = np.argsort(-p)
    ys = y[order]
    tp = np.cumsum(ys)
    total_pos = ys.sum()
    idx = np.arange(1, len(ys) + 1)
    prec = tp / idx
    recall = tp / total_pos
    return float(np.sum(prec[ys == 1] * (recall[ys == 1] - np.concatenate(
        ([0.0], recall[ys == 1][:-1])))))


def _topk(y: np.ndarray, p: np.ndarray, k: int) -> dict:
    k = min(k, len(y))
    order = np.argsort(-p)[:k]
    hits = int(y[order].sum())
    total = int(y.sum())
    return {"K": k, "hits": hits,
            "precision": round(hits / k, 4) if k else np.nan,
            "recall": round(hits / total, 4) if total else np.nan}


def validate_task(task: str, sample: int, seed: int) -> dict:
    subjects = fp.build_subjects(task)
    if sample and len(subjects) > sample:
        subjects = subjects.sample(n=sample, random_state=seed)
    subjects = subjects.reset_index(drop=True)
    y = _y24(subjects)
    if y.sum() == 0:
        return {"task": task, "error": "нет событий в выборке 2026"}
    pr = inf.predict_risk(task, subjects)
    p24 = pr["p24"].to_numpy(np.float64)
    risk30 = pr["risk30"].to_numpy(np.float64)
    r30cal = np.asarray(ml_registry.calibrated_risk(task, risk30), dtype=np.float64)
    out = {
        "task": task,
        "n_subjects": int(len(subjects)),
        "base24_pct": round(y.mean() * 100, 3),
        "pr_auc_24": round(_pr_auc(y, p24), 4),
        "top_p24": {f"K={k}": _topk(y, p24, k) for k in (50, 100, 1000)},
        "top_risk": {f"K={k}": _topk(y, r30cal, k) for k in (50, 100, 1000)},
        "p24_pct": [round(float(v), 4) for v in
                    np.percentile(p24, [50, 90, 95, 99])],
        "risk30_pct": [round(float(v), 4) for v in
                       np.percentile(r30cal, [50, 90, 95, 99])],
    }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="*", default=None)
    ap.add_argument("--sample", type=int, default=15000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    tasks = args.tasks or ["wear", "fire", "access", "sensor"]
    lines = [f"Валидация на потоке H1-2026 (не обучении) | sample={args.sample}",
             "=" * 72]
    for task in tasks:
        try:
            r = validate_task(task, args.sample, args.seed)
        except Exception as exc:  # noqa: BLE001
            r = {"task": task, "error": str(exc)}
        lines.append(f"--- {task} ---")
        for k, v in r.items():
            if k != "task":
                lines.append(f"  {k}: {v}")
    text = "\n".join(lines)
    print(text)
    REPORT.write_text(text, encoding="utf-8")
    print(f"\n[отчёт] -> {REPORT}")


if __name__ == "__main__":
    main()