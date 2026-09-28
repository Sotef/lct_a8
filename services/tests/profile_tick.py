# -*- coding: utf-8 -*-
"""Профилирование одного тика по этапам (что реально доминирует по времени).

Запускать при остановленном сервисе:
  services\\.venv\\Scripts\\python.exe tests\\profile_tick.py [--task wear] [--bucket N]
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.services import feature_pipeline as fp  # noqa: E402
from app.services import inference as inf  # noqa: E402
from app.services import prediction_service as ps  # noqa: E402
from app.workers import simclock  # noqa: E402


def step(name, fn):
    t0 = time.time()
    out = fn()
    dtm = time.time() - t0
    print(f"  {name:28s} {dtm:7.2f} с")
    return out, dtm


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="wear")
    ap.add_argument("--bucket", type=int, default=None)
    ap.add_argument("--rounds", type=int, default=2)
    args = ap.parse_args()
    task = args.task
    db0 = SessionLocal()
    try:
        b = simclock._settings_get(db0, "sim_bucket")
    finally:
        db0.close()
    bucket = args.bucket if args.bucket is not None else int(b)
    simclock._state["panel_max"] = simclock._panel_max_bucket()
    print(f"задача {task}, бакет {bucket} ({simclock.ts_of(bucket)}), "
          f"ядер CPU: {__import__('os').cpu_count()}")

    subs, t = step("warm: модели + субъекты", lambda: simclock._warm(task) or simclock._subjects[task])
    rows, t = step("subjects_for_bucket", lambda: fp.subjects_for_bucket(subs, bucket))
    print(f"  субъектов на бакете: {len(rows)}")

    for rnd in range(1, args.rounds + 1):
        print(f"раунд {rnd}:")
        rb, _ = step("rbam_frame (predict_risk)", lambda: inf.rbam_frame(task, rows))
        S, _ = step("predict_survival_curve", lambda: inf.predict_survival_curve(task, rows))
        db = SessionLocal()
        try:
            step("compute_and_store(factors=False)",
                 lambda: ps.compute_and_store_bucket(task, bucket, db, simclock._models,
                                                     subjects=subs, with_factors=False))
        finally:
            db.close()
        db = SessionLocal()
        try:
            step("compute_and_store(factors=True)",
                 lambda: ps.compute_and_store_bucket(task, bucket, db, simclock._models,
                                                     subjects=subs, with_factors=True))
        finally:
            db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
