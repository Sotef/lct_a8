# -*- coding: utf-8 -*-
"""Живая проверка новых возможностей: дата обслуживания, график работ, p7d, risk7d графа.

Запуск при поднятом сервере (uvicorn app.main:app):
  services\\.venv\\Scripts\\python.exe tests\\check_new_features.py
"""
from __future__ import annotations

import sys

import httpx

B = "http://127.0.0.1:8000/api/v1"
ok = True


def chk(name: str, cond: bool, extra: str = "") -> None:
    global ok
    ok = ok and bool(cond)
    print(f"  {'OK  ' if cond else 'FAIL'} {name} {extra}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    c = httpx.Client(timeout=120)
    tok = c.post(f"{B}/auth/login",
                 json={"username": "dispatcher.alpha",
                       "password": "alpha123"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    # 1. p7d (P(событие ≤ 7 дней)) в прогнозах
    tr = c.get(f"{B}/top-risks?task=wear&k=20&horizon=30d", headers=h).json()
    item = tr["items"][0]
    has_p7d = [i for i in tr["items"] if i.get("p7d") is not None]
    chk("top-risks: p7d присутствует", len(has_p7d) > 0, f"({len(has_p7d)}/{len(tr['items'])})")
    chk("top-risks: недельный риск не меньше суточного", item["p7d"] >= item["p24"] - 1e-9,
        f"p24={item['p24']:.4f} p7d={item['p7d']:.4f}")

    # 2. risk7d по объектам — раскраска графа систем по направлениям
    g = c.get(f"{B}/objects/graph", headers=h).json()
    with7 = [n for n in g["nodes"] if n.get("risk7d")]
    chk("graph: узлы содержат risk7d", len(with7) > 0, f"({len(with7)}/{len(g['nodes'])})")
    chk("graph: risk7d в [0,1]",
        not [1 for n in with7 for v in n["risk7d"].values() if not (0 <= v <= 1)])
    chk("graph: направления ограничены известными",
        all(k in ("fire", "access", "sensor", "wear") for n in with7 for k in n["risk7d"]))

    # 3. тренд по недельному риску
    rh = c.get(f"{B}/meta/risk-history?task=wear&measure=p7d&days=30", headers=h).json()
    chk("risk-history: мера p7d", rh["measure"] == "p7d" and len(rh["rows"]) > 0,
        f"({len(rh['rows'])} точек)")

    # 4. заявка с датой выезда + график обслуживания
    pred = item["id"]
    t = c.post(f"{B}/maintenance/tickets",
               json={"prediction_id": pred, "assign": True, "comment": "проверка",
                     "scheduled_at": "2026-10-05T09:00:00"}, headers=h).json()
    chk("tickets: заявка создана с датой выезда", bool(t.get("scheduled_at")),
        f"id={t.get('id')} at={t.get('scheduled_at')}")
    upd = c.patch(f"{B}/maintenance/tickets/{t['id']}",
                  json={"status": t["status"], "scheduled_at": "2026-10-07T09:00:00"},
                  headers=h).json()
    chk("tickets: дата перенесена", (upd.get("scheduled_at") or "").startswith("2026-10-07"),
        upd.get("scheduled_at"))
    ordered = c.get(f"{B}/maintenance/tickets?order=due&limit=50", headers=h).json()["items"]
    plans = [x.get("plan_at") for x in ordered if x.get("plan_at")]
    chk("tickets: order=due сортирует по плановой дате", plans == sorted(plans),
        f"({len(plans)} дат)")
    obj = item["object_id"]
    byobj = c.get(f"{B}/maintenance/tickets?object_id={obj}&order=due&limit=200",
                  headers=h).json()["items"]
    chk("tickets: фильтр по объекту (график работ объекта)",
        bool(byobj) and all(x["object_id"] == obj for x in byobj), f"({len(byobj)} заявок)")

    # 5. решение «профилактика» с датой выезда -> дата в заявке
    d = c.post(f"{B}/forecasts/{pred}/decision",
               json={"decision": "preventive", "responsible": "dispatcher.alpha",
                     "comment": "плановое ТО", "scheduled_at": "2026-10-12T09:00:00"},
               headers=h).json()
    chk("decision preventive: ok", d.get("ok") is True)
    tl = c.get(f"{B}/maintenance/tickets?object_id={obj}&order=due&limit=200",
               headers=h).json()["items"]
    got = [x for x in tl if (x.get("scheduled_at") or "").startswith("2026-10-12")]
    chk("decision preventive: дата попала в заявку", bool(got),
        f"({len(tl)} заявок объекта, найдено {len(got)})")

    print("=== NEW FEATURES: " + ("ALL OK ===" if ok else "ЕСТЬ ОШИБКИ ==="))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
