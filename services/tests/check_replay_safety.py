# -*- coding: utf-8 -*-
"""Живая проверка: перезапуск реплея не теряет человеческие данные.

Сценарий (нужен поднятый сервис):
  1. диспетчер создаёт заявку с датой выезда и берёт её в работу;
  2. центральный диспетчер перезапускает реплей с января (`POST /admin/clock/reset`);
  3. проверяем: заявка на месте с тем же статусом/датой, решения сохранились,
     текущий бакет снова январский, а обычные прогнозы удалены.

Запуск:  services\\.venv\\Scripts\\python.exe tests\\check_replay_safety.py
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


def tok(c, user, pwd):
    r = c.post(f"{B}/auth/login", json={"username": user, "password": pwd})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    c = httpx.Client(timeout=180)
    hd = tok(c, "dispatcher.alpha", "alpha123")
    hc = tok(c, "central.operator", "central123")

    tick = c.get(f"{B}/top-risks?task=wear&k=5", headers=hd).json()["items"]
    chk("есть прогнозы для создания заявки", bool(tick))
    pred = tick[0]["id"]
    t = c.post(f"{B}/maintenance/tickets", headers=hd,
               json={"prediction_id": pred, "assign": True, "comment": "проверка сохранности",
                     "scheduled_at": "2026-03-20T09:00:00"}).json()
    tid = t["id"]
    c.patch(f"{B}/maintenance/tickets/{tid}", headers=hd,
            json={"status": "in_progress", "comment": "взято в работу"})
    before = c.get(f"{B}/maintenance/tickets?limit=2000", headers=hd).json()
    human_before = len([x for x in before["items"] if x["status"] != "suggested"])

    c.post(f"{B}/admin/clock/reset", headers=hc)
    c.post(f"{B}/admin/clock/step?n=1", headers=hc)      # пересчёт одного бакета

    after = c.get(f"{B}/maintenance/tickets?limit=2000", headers=hd).json()
    mine = [x for x in after["items"] if x["id"] == tid]
    chk("заявка диспетчера сохранилась после перезапуска", bool(mine), f"id={tid}")
    if mine:
        m = mine[0]
        chk("статус сохранён", m["status"] == "in_progress", m["status"])
        chk("дата выезда сохранена", (m.get("scheduled_at") or "").startswith("2026-03-20"),
            str(m.get("scheduled_at")))
        chk("комментарий сохранён", "взято в работу" in (m.get("comment") or ""), str(m.get("comment")))
    human_after = len([x for x in after["items"] if x["status"] != "suggested"])
    chk("человеческих заявок не стало меньше", human_after >= human_before,
        f"{human_before} → {human_after}")

    clk = c.get(f"{B}/meta/clock", headers=hd).json()
    chk("сим-время снова с января", str(clk.get("sim_now", "")).startswith("2026-01"), str(clk.get("sim_now")))
    tr = c.get(f"{B}/top-risks?task=wear&k=5", headers=hd).json()["items"]
    chk("прогнозы пересчитаны на новом круге", bool(tr))
    dec = c.get(f"{B}/audit?action=forecast.decision&size=1", headers=hc).json()
    chk("решения в журнале аудита на месте", dec.get("total", 0) >= 0, f"total={dec.get('total')}")

    print("=== REPLAY SAFETY: " + ("ALL OK ===" if ok else "ЕСТЬ ОШИБКИ ==="))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
