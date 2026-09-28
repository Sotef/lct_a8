# -*- coding: utf-8 -*-
"""Список маршрутов FastAPI -> tests/_routes.json (для статической проверки фронта).

Запуск: services\\.venv\\Scripts\\python.exe tests\\dump_routes.py
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

schema = app.openapi()          # FastAPI 0.14x монтирует роутеры лениво — берём контракт из OpenAPI
paths = sorted(schema.get("paths", {}).keys())
out = pathlib.Path(__file__).resolve().parent / "_routes.json"
out.write_text(json.dumps(paths, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"маршрутов API: {len(paths)} -> {out.name}")
for p in paths:
    print(" ", p)
