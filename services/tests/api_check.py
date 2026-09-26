# -*- coding: utf-8 -*-
"""Комплексная проверка API (login, top-risks, карточка, решение, объекты, планы).

Запуск (с поднятым сервером):  services\\.venv\\Scripts\\python.exe tests\\api_check.py
"""
from __future__ import annotations

import pathlib
import sys

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:8000/api/v1"


def login(client: httpx.Client, username: str, password: str) -> str:
    r = client.post(f"{BASE}/auth/login",
                    json={"username": username, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


def main() -> int:
    fails = []
    with httpx.Client(timeout=60) as c:
        # health
        r = c.get(f"{BASE}/health"); r.raise_for_status()
        print("health:", r.json()["status"], "models:", r.json()["models"])

        tok = login(c, "central.operator", "central123")
        central = {"Authorization": f"Bearer {tok}"}

        saved = {}
        for task in ("fire", "access", "sensor", "wear"):
            r = c.get(f"{BASE}/top-risks", params={"task": task, "k": 10},
                      headers=central)
            r.raise_for_status()
            items = r.json()["items"]
            saved[task] = items
            print(f"top-risks[{task}]: n={len(items)} "
                  f"top_score={items[0]['score'] if items else None} "
                  f"obj={items[0].get('object_id') if items else None}")
            assert all(it["score"] is not None for it in items), f"{task}: score None"

        items_wear = saved["wear"]

        # карточка (живой id из top-risks)
        r = c.get(f"{BASE}/forecasts/{items_wear[0]['id']}", headers=central); r.raise_for_status()
        card = r.json()
        print("card: level=", card["risk_level"], "surv_len=", len(card["horizon"]["surv_points"]),
              "labels=", len(card["horizon"]["labels"]), "last_events=", len(card["last_events"] or []))
        assert len(card["horizon"]["surv_points"]) == len(card["horizon"]["labels"])
        assert card["factors"] is not None, "факторы должны присутствовать (исторический бакет может быть пустым)"
        assert card["last_events"] is not None

        # решение
        r = c.post(f"{BASE}/forecasts/{items_wear[0]['id']}/decision", headers=central,
                   json={"decision": "preventive", "responsible": "central.operator",
                         "comment": "проверка API"})
        r.raise_for_status()
        print("decision:", r.json())

        # список прогнозов
        r = c.get(f"{BASE}/forecasts", params={"task": "wear", "size": 3}, headers=central)
        r.raise_for_status()
        print("forecasts list total:", r.json()["total"])

        # объекты и дерево
        r = c.get(f"{BASE}/objects", headers=central); r.raise_for_status()
        tree = r.json()["tree"]
        print("objects:", len(tree), "риски первого:",
              next((n.get("risks") for n in tree if n.get("risks")), None))
        assert len(tree) == 95

        # риски объекта
        r = c.get(f"{BASE}/objects/5122/risks", params={"task": "wear"}, headers=central)
        r.raise_for_status()
        print("object 5122 risks:", len(r.json()["risks"]))

        # план ТО
        r = c.get(f"{BASE}/maintenance-plan", params={"task": "wear"}, headers=central)
        r.raise_for_status()
        print("maintenance-plan rows:", len(r.json()["rows"]))

        # admin
        r = c.get(f"{BASE}/admin/models", headers=central); r.raise_for_status()
        print("admin/models:", [m["task"] for m in r.json()["models"]])
        r = c.get(f"{BASE}/admin/data/status", headers=central); r.raise_for_status()
        print("admin/data/status sources:", len(r.json()["sources"]))
        r = c.get(f"{BASE}/admin/drift", params={"task": "wear"}, headers=central)
        print("admin/drift quarters:", len(r.json()["quarters"]))

        # RBAC: техник видит только свой подграф объектов
        tok_t = login(c, "tech.alpha", "tech123")
        r = c.get(f"{BASE}/objects", headers={"Authorization": f"Bearer {tok_t}"})
        r.raise_for_status()
        n_tech = len(r.json()["tree"])
        print("tech objects:", n_tech)
        assert n_tech < 95, "техник видит все объекты!"

        # rate-limit login (5 попыток -> 429 на 6-й)
        from app import config  # noqa: E402
        for i in range(config.LOGIN_RATE_LIMIT + 1):
            rr = c.post(f"{BASE}/auth/login",
                        json={"username": "no.such.user", "password": "x"})
        print("rate-limit final code:", rr.status_code)
        fails.append(rr.status_code != 429)

    print("\n=== RESULT:", "FAIL" if any(fails) else "ALL OK", "===")
    return 1 if any(fails) else 0


if __name__ == "__main__":
    sys.exit(main())