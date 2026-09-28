# -*- coding: utf-8 -*-
"""Восстановление заявок из журнала аудита (журнал не удалялся).

Прежняя версия перезапуска реплея удаляла заявки и решения; журнал аудита остался,
поэтому последнее ИЗВЕСТНОЕ состояние по каждому каналу можно вернуть. Скрипт НЕ
выдумывает данные: он берёт только то, что зафиксировано в аудите (task, channel,
object, статус-переход, комментарий, автор, время), а неизвестные поля (score, план,
сроки, риск) оставляет пустыми. Восстановленные заявки помечаются в комментарии.

Запуск (по умолчанию — dry-run, только показать):
  services\\.venv\\Scripts\\python.exe tests\\restore_tickets_from_audit.py
  services\\.venv\\Scripts\\python.exe tests\\restore_tickets_from_audit.py --apply
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app import models_db as m  # noqa: E402
from app.database import SessionLocal  # noqa: E402

MARK = "восстановлено из журнала аудита"
# записи, сделанные автотестами/смоуком, восстанавливать не нужно
TEST_USERS = {"smoke.test", "central.t", "disp.t", "tech.t"}
TEST_COMMENT = ("smoke", "смоук", "test", "тест", "фронт", "probe", "audit")


def is_test_noise(task: str, ch: str, f: dict, users: dict) -> bool:
    if ch.startswith("CH") or ch.startswith("OBJ"):
        return True
    if users.get(f.get("user_id")) in TEST_USERS:
        return True
    c = (f.get("comment") or "").lower()
    return any(w in c for w in TEST_COMMENT)


def collect(db) -> dict:
    """{(task, channel): факты из аудита} — последнее известное состояние."""
    facts: dict = {}

    def touch(action: str, det: dict, ts, user_id, entity_id):
        task, ch = det.get("task"), det.get("channel_id")
        if not task or not ch:
            return
        f = facts.setdefault((task, ch), {"action": action, "obj": det.get("object_id"),
                                          "status": None, "comment": None, "ts": ts,
                                          "user_id": user_id, "ticket_id": entity_id,
                                          "decision": None})
        if det.get("object_id"):
            f["obj"] = det["object_id"]
        if ts and (f["ts"] is None or ts >= f["ts"]):
            f["ts"] = ts
            f["user_id"] = user_id or f["user_id"]
        if action == "ticket.status":
            f["status"] = det.get("to") or f["status"]
            if det.get("comment"):
                f["comment"] = det["comment"]
        if action == "forecast.decision":
            f["decision"] = det.get("decision")
            if det.get("decision") == "preventive":
                f["status"] = "assigned"
            if det.get("comment"):
                f["comment"] = det["comment"]

    for r in (db.query(m.AuditLog)
              .filter(m.AuditLog.action.in_(("ticket.status", "ticket.create", "forecast.decision")))
              .order_by(m.AuditLog.id.asc()).all()):
        det = r.detail or {}
        if not isinstance(det, dict):
            continue
        touch(r.action, det, r.created_at, r.user_id, r.entity_id)
    return facts


def main(apply: bool) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    db = SessionLocal()
    try:
        facts = collect(db)
        existing = {(t.task, t.channel_id) for t in db.query(m.MaintenanceTask).all()}
        users = {u.id: u.username for u in db.query(m.User).all()}
        todos, skipped = [], []
        for k, v in facts.items():
            if k in existing or not v.get("status"):
                continue
            (skipped if is_test_noise(k[0], k[1], v, users) else todos).append((k, v))
        print(f"каналов с историей в аудите: {len(facts)}; заявки уже есть у: {len(facts) - len(todos) - len(skipped)}; "
              f"к восстановлению: {len(todos)}; пропущено как тестовые: {len(skipped)}")
        from app import task_cfg
        print(f"\n{'task':<8}{'channel':<12}{'object':<10}{'статус':<12}{'автор':<18}комментарий")
        for (task, ch), f in sorted(todos, key=lambda kv: kv[1]["ts"] or 0):
            print(f"{task:<8}{ch:<12}{str(f.get('obj') or '—'):<10}{str(f.get('status')):<12}"
                  f"{str(users.get(f.get('user_id')) or '—'):<18}{str(f.get('comment') or '')[:40]}")
        if not apply:
            print("\n(dry-run: для записи добавьте --apply)")
            return 0
        n = 0
        for (task, ch), f in todos:
            if task not in task_cfg.ALL_TASKS:
                continue
            db.add(m.MaintenanceTask(
                task=task, channel_id=ch, object_id=str(f.get("obj") or ""),
                status=f["status"], source="decision" if f.get("decision") else "manual",
                assigned_to=f.get("user_id"),
                comment=f"{MARK}: {f.get('comment') or f.get('decision') or f['status']}",
                created_at=f["ts"], updated_at=f["ts"]))
            n += 1
        db.commit()
        print(f"\nвосстановлено заявок: {n}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
