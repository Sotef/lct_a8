# -*- coding: utf-8 -*-
"""UI-контракт: для КАЖДОЙ роли проверяем все страницы и наличие обязательных
элементов/полей, которые фронт читает (запросы — как их делает JS).

Ловит классы багов: 403 «нет доступа» на своей странице, пустые списки,
отсутствующие поля (undefined в JS), рассинхрон labels/surv_points.
Запуск при поднятом сервере: python tests/ui_contract_check.py
"""
import httpx
import sys

B = "http://127.0.0.1:8000/api/v1"
ok = True


def chk(name, cond, extra=""):
    global ok
    print(("  OK " if cond else "  FAIL ") + name, extra if not cond else "")
    ok = ok and cond


def fnum(v):
    return isinstance(v, (int, float))


def get(path):
    def _run(c, h):
        r = c.get(B + path, headers=h)
        return r.status_code, (r.json() if r.status_code == 200 else None)
    return _run


def post(path, json):
    def _run(c, h):
        r = c.post(B + path, headers=h, json=json)
        return r.status_code, (r.json() if r.status_code == 200 else None)
    return _run


PAGES = {
    "Дашборд": [
        ("GET", "/meta/summary", "summary",
         lambda s: all(t in s and fnum(s[t].get("n")) and "bucket" in s[t]
                       for t in ("fire", "access", "sensor", "wear"))),
        ("GET", "/meta/risk-history?task=wear&n=20", "hist",
         lambda s: s["rows"] and all(k in s["rows"][0] for k in ("avg_risk", "max_risk", "n", "bucket_ts"))),
        ("GET", "/meta/clock", "clock",
         lambda s: s.get("mode") == "replay-2026" and s.get("bucket") is not None),
        ("GET", "/top-risks?task=wear&k=5&horizon=72h", "top",
         lambda s: s["items"] and all(k in s["items"][0] for k in (
             "id", "p24", "p72", "risk30", "risk_used", "score",
             "название_объекта", "тип_датчика", "event_flag"))),
        ("GET", "/top-objects?task=wear&k=5&horizon=72h", "topobj",
         lambda s: s["items"] and all(k in s["items"][0] for k in (
             "object_id", "название_объекта", "вклад", "каналов", "риск_макс"))
         and s["items"][0]["top_channels"]),
    ],
    "Объекты": [
        ("GET", "/objects", "tree",
         lambda s: s["tree"] and all(k in s["tree"][0] for k in (
             "object_id", "name", "type", "level", "risks"))),
    ],
    "Граф систем": [
        ("GET", "/objects/graph", "graph",
         lambda s: s["nodes"] and s["hubs"] and all(k in s["nodes"][0] for k in ("id", "name", "risk", "hubs"))),
    ],
    "Журнал": [
        ("GET", "/forecasts?task=wear&page=1&size=5&horizon=72h", "list",
         lambda s: s["items"] and all(k in s["items"][0] for k in (
             "id", "p24", "p72", "risk30", "risk_used", "exp_days", "score",
             "plan", "bucket_ts", "название_объекта"))),
    ],
    "План ТО": [
        ("GET", "/maintenance-plan?task=wear", "plan",
         lambda s: s["rows"] and all(k in s["rows"][0] for k in (
             "plan", "тип_датчика", "каналов", "риск_средний", "score_сумма", "exp_days_медиана"))),
    ],
    "Заявки": [
        ("GET", "/maintenance/tickets?limit=20", "tickets",
         lambda s: "items" in s and all(k in (s["items"][0] if s["items"] else {}) for k in (
             "status", "status_ru", "priority", "source", "due_to")) if s["items"] else True),
        ("GET", "/maintenance/summary", "summary",
         lambda s: "by_status" in s and "open" in s),
    ],
}
# ручки, доступные не всем ролям: (путь, роли, валидатор)
RESTRICTED = [
    ("/audit?size=5", ("dispatcher", "central"),
     lambda s: "items" in s and "total" in s),
    ("/audit/actions", ("dispatcher", "central"), lambda s: "actions" in s),
    ("/admin/system", ("central",), lambda s: "counts" in s and "log" in s),
    ("/admin/logs?limit=5", ("central",), lambda s: "last_id" in s),
    ("/admin/models", ("central",), lambda s: "models" in s),
]

ROLES = [("central.operator", "central123", "central"),
         ("dispatcher.alpha", "alpha123", "dispatcher"),
         ("tech.alpha", "tech123", "tech")]

c = httpx.Client(timeout=60)
cards_checked = 0
for user, pwd, role in ROLES:
    r = c.post(f"{B}/auth/login", json={"username": user, "password": pwd})
    print(f"--- {user} ({role}) ---")
    if r.status_code != 200:
        chk(f"{role}/login", False, f"status {r.status_code}")
        continue
    h = {"Authorization": "Bearer " + r.json()["access_token"]}
    for page, checks in PAGES.items():
        page_ok = True
        for method, path, name, validator in checks:
            code, data = get(path)(c, h)
            if not (code == 200 and data is not None and validator(data)):
                page_ok = False
                chk(f"{role}/{page}/{name}", False, f"status={code}")
        chk(f"{role}/{page}: все элементы на месте", page_ok)

    # ручки с ограничением по ролям
    for path, roles, validator in RESTRICTED:
        code, data = get(path)(c, h)
        if role in roles:
            chk(f"{role} доступ к {path}", code == 200 and validator(data), f"status={code}")
        else:
            chk(f"{role}: {path} закрыт", code == 403, f"status={code}")

    fl = c.get(f"{B}/forecasts?task=wear&page=1&size=5&horizon=30d", headers=h)
    if fl.status_code == 200 and fl.json()["items"]:
        card = c.get(f"{B}/forecasts/{fl.json()['items'][0]['id']}", headers=h).json()
        surv = (card.get("horizon") or {}).get("surv_points") or []
        chk(f"{role}/карточка: S(t)/labels согласованы",
            len(surv) == 8 and len((card.get("horizon") or {}).get("labels", [])) == 8)
        probs = card.get("probabilities") or {}
        chk(f"{role}/карточка: p24/p72/risk_used",
            all(k in probs for k in ("p24", "p72", "risk30", "risk_used")))
        chk(f"{role}/карточка: объект/рекомендация/план",
            (card.get("object") or {}).get("name") is not None
            and card.get("recommended_action") and (card.get("rbam") or {}).get("plan"))
        cards_checked += 1

    if role in ("central", "dispatcher") and fl.status_code == 200 and fl.json()["items"]:
        pid = fl.json()["items"][0]["id"]
        d = c.post(f"{B}/forecasts/{pid}/decision", headers=h,
                   json={"decision": "confirm", "responsible": user, "comment": "ui-contract"})
        chk(f"{role}/decision POST", d.status_code == 200 and d.json().get("ok"))

# доступы, которые ДОЛЖНЫ быть закрыты
h = {"Authorization": "Bearer " + c.post(f"{B}/auth/login",
     json={"username": "tech.alpha", "password": "tech123"}).json()["access_token"]}
chk("tech/users закрыт", c.get(f"{B}/auth/admin/users", headers=h).status_code == 403)
chk("tech/create-user закрыт", c.post(f"{B}/auth/admin/create-user", headers=h,
    json={"username": "x", "password": "xxxx", "role": "tech"}).status_code == 403)

# навигация в JS соответствует матрице ролей (VIEWS: roles[])
import pathlib
appjs = (pathlib.Path(__file__).resolve().parent.parent / "app/web/js/app.js").read_text(encoding="utf-8")
chk("nav: описана матрица ролей разделов", "roles: [" in appjs and '"dashboard"' in appjs)
chk("nav: план ТО и заявки доступны технику",
    bool(__import__("re").search(r'\{\s*v:\s*"plan"[^}]*roles:\s*\[[^\]]*"tech"', appjs))
    and bool(__import__("re").search(r'\{\s*v:\s*"tickets"[^}]*roles:\s*\[[^\]]*"tech"', appjs)))
chk("nav: аудит только для dispatcher/central",
    bool(__import__("re").search(r'\{\s*v:\s*"audit"[^}]*roles:\s*\[[^\]]*"central"', appjs)))
chk("nav: система и пользователи только central",
    bool(__import__("re").search(r'\{\s*v:\s*"sys"[^}]*roles:\s*\["central"\]', appjs))
    and bool(__import__("re").search(r'\{\s*v:\s*"users"[^}]*roles:\s*\["central"\]', appjs)))

print("=== UI CONTRACT:", "ALL OK" if ok else "FAIL", f"({cards_checked} карточек) ===")
sys.exit(0 if ok else 1)
