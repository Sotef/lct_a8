# -*- coding: utf-8 -*-
"""Проверка развёрнутого сервиса (docker compose / прод): API по ролям + PWA-раздача.

Запуск на хосте или в контейнере:
  services\\.venv\\Scripts\\python.exe services\\scripts\\verify_deploy.py
  docker compose exec -T api python scripts/verify_deploy.py

Переменные: BASE_URL (по умолчанию http://127.0.0.1:8000),
            VERIFY_USER / VERIFY_PASSWORD (по умолчанию central.operator / central123).
Код возврата 0 — все проверки прошли.
"""
from __future__ import annotations

import os
import sys

import httpx

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API = BASE + "/api/v1"
USER = os.getenv("VERIFY_USER", "central.operator")
PASSWORD = os.getenv("VERIFY_PASSWORD", "central123")

ok = True


def chk(name: str, cond: bool, extra: str = "") -> None:
    global ok
    print(("  OK   " if cond else "  FAIL ") + name + ("" if cond else " :: " + str(extra)[:300]))
    ok = ok and cond


def main() -> int:
    with httpx.Client(timeout=30.0) as c:
        r = c.get(API + "/health")
        j = r.json() if r.status_code == 200 else {}
        chk("GET /health", r.status_code == 200 and j.get("status") == "ok", r.text)
        chk("models загружены (fire/access/sensor/wear)",
            all(j.get("models", {}).get(t) == "ok" for t in ("fire", "access", "sensor", "wear")),
            j.get("models"))

        r = c.post(API + "/auth/login", json={"username": USER, "password": PASSWORD})
        chk(f"POST /auth/login ({USER})", r.status_code == 200, r.text)
        if r.status_code != 200:
            print("\n=== DEPLOY VERIFY: FAIL (нет токена) ===")
            return 1
        tok = r.json()["access_token"]
        h = {"Authorization": "Bearer " + tok}

        r = c.get(API + "/auth/me", headers=h)
        chk("GET /auth/me + RBAC-роль", r.status_code == 200 and r.json().get("role"), r.text)

        for path, extra_name in [
            ("/alerts?limit=5", "Алерты (серверный журнал/fallback)"),
            ("/meta/client-config", "Конфиг мобильного профиля"),
            ("/top-risks?task=wear&k=3&horizon=72h", "Топ-риски"),
            ("/maintenance/tickets?limit=3", "Заявки (список+курсор)"),
            ("/maintenance/summary", "Сводка заявок"),
            ("/objects", "Объекты"),
            ("/forecasts?task=wear&page=1&size=2", "Журнал прогнозов"),
            ("/meta/summary", "KPI дашборда"),
            ("/push/vapid-public-key", "VAPID-ключ (push)"),
        ]:
            r = c.get(API + path, headers=h)
            chk(f"GET {path} — {extra_name}", r.status_code == 200, r.text)

        r = c.post(API + "/admin/alerts/run?force=true", headers=h)
        chk("POST /admin/alerts/run (правило алертов)", r.status_code == 200 and "fired" in r.json(), r.text)

        # SPA и PWA-раздача (одним origin, без CDN)
        r = c.get(BASE + "/")
        chk("SPA / (index.html)", r.status_code == 200 and "mc_theme" in r.text, r.status_code)
        chk("SPA: mobile.css подключён", r.status_code == 200 and "/css/mobile.css" in r.text)
        r = c.get(BASE + "/sw.js")
        chk("GET /sw.js (service worker)",
            r.status_code == 200 and "Service-Worker-Allowed" in r.headers
            and "javascript" in r.headers.get("content-type", ""), dict(r.headers))
        r = c.get(BASE + "/manifest.webmanifest")
        chk("GET /manifest.webmanifest (PWA)",
            r.status_code == 200 and "manifest" in r.headers.get("content-type", ""),
            r.headers.get("content-type"))
        r = c.get(BASE + "/docs")
        chk("GET /docs (Swagger)", r.status_code == 200, r.status_code)

    print("\n=== DEPLOY VERIFY: " + ("ALL OK" if ok else "FAIL") + " ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
