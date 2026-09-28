# -*- coding: utf-8 -*-
"""Замер стоимости одного тика демо-прокрута (SHAP-факторы vs быстрый расчёт).

Запускать при остановленном сервисе (пишет прогнозы в БД, идемпотентно по бакету):
  services\\.venv\\Scripts\\python.exe tests\\bench_tick.py [--bucket N] [--task wear]

Замеры на данных 2026 (16 ядер, 4 задачи, ~540 каналов на бакет):
  fast+seq    ~0.6 с   без SHAP, задачи последовательно      <- рекомендуемый режим демо
  fast+par    ~0.5 с   без SHAP, задачи параллельно
  factors+seq ~114 с   со SHAP (как было) — SHAP ~43 с на задачу
  factors+par ~117 с   со SHAP, параллельно (выигрыша нет: SHAP и так грузит все ядра)

Вывод: время тика определяют SHAP-факторы (≈99.5%), а не ядра и не инференс
(predict_proba ~0.02 с на задачу). Отсюда переключатель «быстрый расчёт» в UI.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.workers import simclock  # noqa: E402


def cur_bucket() -> int:
    db = SessionLocal()
    try:
        b = simclock._settings_get(db, "sim_bucket")
    finally:
        db.close()
    return int(b) if b is not None else simclock.bucket_of(
        __import__("datetime").datetime.fromisoformat("2026-01-01T00:00:00"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", type=int, default=None)
    ap.add_argument("--task", default=None, help="замер только одной задачи")
    ap.add_argument("--combos", default="4", help="сколько вариантов считать (4 = все)")
    args = ap.parse_args()
    bucket = args.bucket if args.bucket is not None else cur_bucket()
    simclock._state["panel_max"] = simclock._panel_max_bucket()
    print(f"бакет {bucket} ({simclock.ts_of(bucket)}), потоков: 4 задачи, "
          f"CPU: {__import__('os').cpu_count()} ядер")

    t0 = time.time()
    for t in (simclock.TASKS if not args.task else (args.task,)):
        simclock._warm(t)
    print(f"прогрев (модели + субъекты + панели): {time.time() - t0:.1f} с\n")

    # (fast, parallel, подпись): fast=True -> with_factors=False
    combos = [(True, False, "fast+seq"), (True, True, "fast+par"),
              (False, False, "factors+seq"), (False, True, "factors+par")]
    for i, (fast, parallel, name) in enumerate(combos):
        if i >= int(args.combos):
            break
        simclock._state["fast"] = fast
        simclock._state["parallel"] = parallel
        tasks = (args.task,) if args.task else simclock.TASKS
        per = {}
        t0 = time.time()
        if parallel and len(tasks) > 1:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
                for tt, res in ex.map(lambda x: (x, simclock._compute_task(x, bucket, not fast)), tasks):
                    per[tt] = res
        else:
            for tt in tasks:
                per[tt] = simclock._compute_task(tt, bucket, not fast)
        dtm = time.time() - t0
        print(f"{name:14s} {dtm:6.1f} с  " + " ".join(f"{k}={v}" for k, v in per.items()))
    print("\nПримечание: 'fast' не сохраняет SHAP-факторы (в карточке прогноза будет "
          "пометка «факторы не сохранены»); качество прогноза не меняется.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
