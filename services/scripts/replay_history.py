# -*- coding: utf-8 -*-
"""Пересчёт истории прогнозов на последних N бакетах (для графиков UI).

Запуск:  services\\.venv\\Scripts\\python.exe scripts\\replay_history.py [--buckets 40]
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, init_db  # noqa: E402
from app.workers import ingestion  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--buckets", type=int, default=40)
    ap.add_argument("--tasks", nargs="+", default=None)
    args = ap.parse_args()
    init_db()
    db = SessionLocal()
    try:
        out = ingestion.run_replay(db, tasks=args.tasks,
                                   bucket_count=args.buckets)
        for task, r in out.items():
            if "error" in r:
                print(f"[{task}] ERROR: {r['error']}")
            else:
                print(f"[{task}] buckets={r['bucket_count']} "
                      f"first={r['first']} last={r['last']} "
                      f"elapsed={r['elapsed_sec']}s")
    finally:
        db.close()


if __name__ == "__main__":
    main()