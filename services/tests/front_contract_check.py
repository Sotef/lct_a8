import httpx, json, sys, time

B = "http://127.0.0.1:8000/api/v1"
c = httpx.Client(timeout=60)
ok = True


def lg(user, pwd):
    """Логин с показом статуса (rate-limit/загрузка сервера — видно сразу)."""
    for attempt in range(3):
        r = c.post(f"{B}/auth/login", json={"username": user, "password": pwd})
        if r.status_code == 200:
            return r.json()["access_token"]
        print(f"  login {user}: {r.status_code} {r.text[:120]}")
        time.sleep(20)
    raise SystemExit(f"login failed for {user}")


def chk(name, cond, extra=""):
    global ok
    print(("  OK " if cond else "  FAIL ") + name, extra)
    ok = ok and cond


# 1. Все роли: ключевые запросы фронт-контракта (как это делает UI)
for user, pwd in [("central.operator", "central123"), ("dispatcher.alpha", "alpha123"),
                  ("tech.alpha", "tech123")]:
    tok = lg(user, pwd)
    h = {"Authorization": "Bearer " + tok}
    role = c.get(f"{B}/auth/me", headers=h).json()["role"]
    print(f"--- {user} ({role}) ---")
    for name, path in [
        ("summary", "/meta/summary"),
        ("risk-history", "/meta/risk-history?task=wear&n=10"),
        ("objects", "/objects"),
        ("graph", "/objects/graph"),
        ("forecasts", "/forecasts?task=wear&page=1&size=5"),
        ("plan", "/maintenance-plan?task=wear"),
        ("top-risks", "/top-risks?task=wear&k=3"),
    ]:
        r = c.get(B + path, headers=h)
        print(f"  {name}: {r.status_code}", "" if r.status_code == 200 else r.text[:80])
        chk(f"{role}/{name}", r.status_code == 200 or
            (role == "tech" and name in ("top-risks",)))  # tech: top-risks закрыт по RBAC

# 1b. сим-часы
r = c.get(f"{B}/meta/clock", headers={"Authorization": "Bearer " + lg("tech.alpha", "tech123")}).json()
chk("meta/clock replay-2026", r.get("mode") == "replay-2026" and r.get("bucket") is not None,
    f"sim_now={r.get('sim_now')}")

# 2. central-проверки: объектные поля, карточка, решение, admin/users
tok = lg("central.operator", "central123")
h = {"Authorization": "Bearer " + tok}
tr = c.get(f"{B}/top-risks?task=wear&k=5", headers=h).json()
it = tr["items"][0]
chk("top-risks объектные поля", all(k in it for k in (
    "название_объекта", "район", "тип_датчика", "название_датчика",
    "тег_инж_системы", "инж_система")))
fid = it["id"]  # запись с последнего бакета — SHAP сохранён
card = c.get(f"{B}/forecasts/{fid}", headers=h).json()
chk("карточка: probabilities/horizon/factors/object",
    "probabilities" in card and len(card["horizon"]["surv_points"]) == 8
    and card["factors"] is not None and "name" in card["object"])
dec = c.post(f"{B}/forecasts/{fid}/decision", headers=h,
             json={"decision": "preventive", "responsible": "central.operator",
                   "comment": "фронт-смоук"})
chk("decision POST", dec.status_code == 200 and dec.json().get("ok"))
us = c.get(f"{B}/auth/admin/users", headers=h).json()
chk("admin/users список", len(us["users"]) >= 4)
nu = c.post(f"{B}/auth/admin/create-user", headers=h,
            json={"username": "smoke.test", "password": "smoke1234", "role": "dispatcher"})
chk("create-user", nu.status_code in (200, 409))

print("=== FRONT CONTRACT:", "ALL OK" if ok else "FAIL", "===")
sys.exit(0 if ok else 1)

