# -*- coding: utf-8 -*-
"""Покрытие панелей сырым кэшем (важно для демо-прокрута).

Если панель построена до того, как в кэш догрузились новые бакеты, для этих
бакетов субъектов не найдётся и прогноз не появится (n_subjects=0) — сервис не
упадёт, но тик «пройдёт вхолостую». Скрипт показывает разрыв и время сборки.

Запуск: services\\.venv\\Scripts\\python.exe tests\\check_panel_coverage.py
"""
from __future__ import annotations

import pathlib
import sys
import time

import pandas as pd

# консоль Windows (cp1251) — переводим вывод в utf-8 (см. smoke_new_api.py)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.adapters.journal import bucket_to_timestamp  # noqa: E402

TASKS = ("fire", "access", "sensor", "wear")


def ts(b) -> str:
    try:
        return bucket_to_timestamp(int(b)).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return str(b)


def main() -> int:
    ok = True
    raw = config.RAW_DIR / "buckets_2026.parquet"
    if not raw.exists():
        print(f"нет кэша сырых бакетов: {raw}")
        return 2
    t0 = time.time()
    cache = pd.read_parquet(raw, columns=["бакет"])["бакет"]
    cmin, cmax = int(cache.min()), int(cache.max())
    print(f"кэш сырых бакетов: {cmin}..{cmax} ({ts(cmin)} .. {ts(cmax)}), строк {len(cache)}, "
          f"{raw.stat().st_size / 1e6:.1f} МБ ({time.time() - t0:.1f} с)")
    for task in TASKS:
        p = config.PANEL_DIR / f"subdaily_panel_{task}6h_2026.csv"
        if not p.exists():
            print(f"  {task:7s} панели НЕТ ({p.name})")
            ok = False
            continue
        t1 = time.time()
        b = pd.read_csv(p, usecols=["бакет"], dtype={"бакет": "int64"})["бакет"]
        pmin, pmax = int(b.min()), int(b.max())
        lag = cmax - pmax
        flag = "OK" if lag <= 0 else f"ОТСТАЁТ на {lag} бакет(ов)"
        print(f"  {task:7s} панель {pmin}..{pmax} ({ts(pmin)} .. {ts(pmax)}) строк {len(b)} "
              f"[{flag}] ({time.time() - t1:.1f} с)")
        ok = ok and lag <= 0
    # z-статистики и схема
    for task in TASKS:
        for name in (f"z_stats_{task}.csv", f"cat_codes_{task}.json"):
            f = config.DATA_DIR / name
            if not f.exists():
                print(f"  отсутствует {name}")
                ok = False
    print("=== ПОКРЫТИЕ ПАНЕЛЕЙ:", "OK" if ok else "ЕСТЬ РАЗРЫВ (пересобрать панели)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
