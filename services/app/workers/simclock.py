# -*- coding: utf-8 -*-
"""Симулируемые часы сервиса (режим реплея данных 2026 года).

SIM_CLOCK=1 (config): «сейчас» сервиса — симулированное время, старт 2026-01-01
00:00. Каждые SIM_TICK_REAL_SEC секунд реального времени сим-время продвигается
на 6ч (один бакет) и все 4 задачи пересчитываются на нём: прогнозы «поступают
в поток», тренд риска и KPI накапливаются в реальном времени.

Состояние (текущий сим-бакет) хранится в settings.sim_bucket и переживает рестарт.
Первый запуск с пустым sim_bucket сбрасывает старый реплей (predictions/decisions/
maintenance_tasks) и начинает с 2026-01-01 00:00.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time

import pandas as pd

from .. import config
from .. import models_db as dbm
from ..database import SessionLocal
from ..services import feature_pipeline as fp
from ..services import ml_registry, prediction_service
from . import ingestion

log = logging.getLogger("simclock")

TASKS = ("fire", "access", "sensor", "wear")
_state: dict = {
    "bucket": None, "panel_max": None, "tick_sec": config.SIM_TICK_REAL_SEC,
    "last_tick": None, "next_tick": None, "running": False,
    "computing": False, "error": None, "last_counts": None,
    "paused": False,          # пауза реплея (см. pause()/resume())
    "step_budget": None,      # ручной шаг: сколько бакетов просчитать без ожидания тика
    "step_restore_paused": False,
    "fast": False,            # быстрый расчёт: без SHAP-факторов (~×100 к скорости тика)
    "parallel": False,        # задачи параллельно (обычно не ускоряет: узкое место — SHAP)
    "last_tick_sec": None,    # сколько занял последний тик (реальное время)
}
_subjects: dict = {}
_models: dict = {}
_feed = None                      # JournalFeed для режима живой подачи (SIM_FEED=1)
_warm_lock = threading.Lock()
_stop = threading.Event()
_wake = threading.Event()     # досрочное пробуждение цикла (шаг/сброс/пауза)
_thread: threading.Thread | None = None
_db = None  # сессия текущего тика


def bucket_of(d: dt.datetime) -> int:
    """6-часовой бакет от эпохи (та же сетка, что research/features)."""
    return int((d - dt.datetime(1970, 1, 1)).total_seconds() // (6 * 3600))


def ts_of(bucket: int) -> str:
    return ingestion._bucket_ts(int(bucket)).strftime("%Y-%m-%d %H:%M")


def _settings_get(db, key: str):
    row = db.get(dbm.Setting, key)
    return row.value if row is not None else None


def _settings_set(db, key: str, value) -> None:
    row = db.get(dbm.Setting, key)
    if row is None:
        row = dbm.Setting(key=key)
        db.add(row)
    row.value = value
    db.commit()


def _fresh_start(db) -> int:
    """Сброс старого реплея и установка стартового сим-бакета (01.01.2026 00:00).

    Перезапуск круга касается **только прогнозов** — они воспроизводимы.
    Человеческие данные сохраняются:
      * решения диспетчера остаются как есть; прогнозы, на которые они ссылаются,
        помечаются `pinned=1` (признаки + метка для дообучения) и исключаются из
        запросов «текущего бакета» (`latest_bucket_ts` и др.);
      * заявки, которых коснулся человек (назначены/в работе/выполнены/отменены, созданы
        вручную или решением «профилактика», с датой выезда/исполнителем/комментарием),
        сохраняются; у них снимается ссылка на удалённый прогноз — риск, срок, план и
        приоритет остаются в самой заявке;
      * удаляются только необработанные предложения автоформирования
        (source='auto', status='suggested', без исполнителя/даты/комментария): модель
        воспроизведёт их на новом круге, а иначе они бы блокировали создание новых
        предложений по тем же каналам;
      * журнал аудита не трогается никогда.
    """
    from sqlalchemy import and_, not_
    start = bucket_of(dt.datetime.fromisoformat(config.SIM_START))
    T = dbm.MaintenanceTask
    machine = and_(T.source == "auto", T.status == "suggested",
                   T.assigned_to.is_(None), T.scheduled_at.is_(None), T.comment.is_(None))
    # 1) прогнозы, на которые ссылаются решения, «закрепляем» (метки для дообучения)
    pinned_ids = [r[0] for r in db.query(dbm.Decision.prediction_id).distinct().all() if r[0]]
    n_pinned = 0
    if pinned_ids:
        n_pinned = (db.query(dbm.Prediction)
                    .filter(dbm.Prediction.id.in_(pinned_ids))
                    .update({"pinned": 1}, synchronize_session=False))
    # 2) человеческие заявки сохраняем, снимая ссылку на удаляемый прогноз
    n_keep = (db.query(T).filter(not_(machine))
              .update({"prediction_id": None}, synchronize_session=False))
    n_machine = db.query(T).filter(machine).delete(synchronize_session=False)
    # 3) прогнозы без метки удаляются — реплей пересчитает их на новом круге
    #    (условие current_only защищает и от строк с NULL в pinned)
    n_pred = db.query(dbm.Prediction).filter(dbm.current_only()).delete(synchronize_session=False)
    _settings_set(db, "sim_bucket", start)
    db.commit()
    log.info("sim-clock fresh start: bucket=%s (%s); predictions wiped=%s pinned=%s; "
             "tickets kept=%s, machine suggestions removed=%s; решения и аудит сохранены",
             start, ts_of(start), n_pred, n_pinned, n_keep, n_machine)
    return start


def _panel_max_bucket() -> int:
    """Максимальный бакет данных: конец реплея.

    SIM_FEED=1 — горизонт задаёт сам журнал (последняя строка), т.к. панели строятся
    на каждый тик только из уже «наступивших» данных.
    """
    if config.SIM_FEED:
        from . import stream
        return stream.journal_end_bucket()
    mx = None
    for task in TASKS:
        p = config.PANEL_DIR / f"subdaily_panel_{task}6h_2026.csv"
        if not p.exists():
            continue
        b = int(pd.read_csv(p, usecols=["бакет"])["бакет"].max())
        mx = b if mx is None else max(mx, b)
    return mx if mx is not None else bucket_of(dt.datetime(2026, 6, 30, 18))


def _warm(task: str):
    """Ленивая инициализация: модели + субъекты задачи (по одному разу)."""
    if task not in _models:
        _models[task] = ml_registry.load_registry_task(task)
    if task not in _subjects:
        _subjects[task] = fp.build_subjects(task, recompute_panel=False)


# --- живая подача (SIM_FEED=1) ------------------------------------------------
def _get_feed():
    """Ленивый запуск потоковой подачи журнала (только при SIM_FEED=1)."""
    global _feed
    if _feed is None:
        from . import stream
        _feed = stream.JournalFeed()
        log.info("stream feed: журнал=%s, кэш=%s, панели=%s, чанк=%s строк",
                 _feed.adapter.source, config.RAW_DIR, config.PANEL_DIR, _feed.chunksize)
    return _feed


def _reset_feed() -> None:
    """Новый круг реплея в режиме подачи: забыть кэш/панели и читать журнал заново."""
    global _feed
    _feed = None
    removed = 0
    for d, pat in ((config.RAW_DIR, "*.parquet"), (config.PANEL_DIR, "*.csv")):
        for p in d.glob(pat):
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    for p in config.RAW_DIR.glob("checkpoint_*.json"):
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    for task in TASKS:                 # субъекты больше не валидны
        _subjects.pop(task, None)
    if removed:
        log.info("stream feed: сброшено %s файлов кэша/панелей (новый круг)", removed)


def _compute_bucket(bucket: int) -> dict:
    """Прогноз всех задач на бакете. `parallel` — задачи параллельно (CatBoost
    отпускает GIL), `fast` — без SHAP-факторов (в карточке будет честная пометка)."""
    with_factors = not _state["fast"]
    tasks = list(TASKS)
    if not _state["parallel"] or len(tasks) == 1:
        out = {}
        for task in tasks:
            out[task] = _compute_task(task, bucket, with_factors)
        return out
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="tick") as ex:
        return dict(ex.map(lambda t: (t, _compute_task(t, bucket, with_factors)), tasks))


def _compute_task(task: str, bucket: int, with_factors: bool):
    db = SessionLocal()
    try:
        if config.SIM_FEED:
            # живая подача: признаки пересобираются из накопленного кэша на каждом тике
            with _warm_lock:
                if task not in _models:
                    _models[task] = ml_registry.load_registry_task(task)
            res = prediction_service.compute_and_store_bucket(
                task, bucket, db, _models, subjects=None,
                recompute_panel=config.SIM_FEED_REBUILD, with_factors=with_factors)
        else:
            with _warm_lock:
                _warm(task)
            res = prediction_service.compute_and_store_bucket(
                task, bucket, db, _models, subjects=_subjects[task],
                with_factors=with_factors)
        if not res.get("n_subjects"):
            if config.SIM_FEED:
                log.info("bucket %s task %s: событий этой задачи в бакете пока нет "
                         "(живая подача, накопится на следующих тиках)", bucket, task)
            else:
                log.warning("bucket %s task %s: субъектов нет — панель не покрывает бакет "
                            "(пересоберите панели: scripts/run_demo.py --recompute-panel)",
                            bucket, task)
        return res.get("n_stored", 0)
    except Exception as exc:  # noqa: BLE001
        log.exception("tick %s task %s failed", bucket, task)
        return f"error: {exc}"
    finally:
        db.close()


def _loop() -> None:
    global _db
    db = SessionLocal()
    try:
        b = _settings_get(db, "sim_bucket")
        if b is None:
            b = _fresh_start(db)
            if config.SIM_FEED:
                _reset_feed()          # первый запуск: подача начинается «с чистого листа»
        _state["bucket"] = int(b)
    finally:
        db.close()
    _state["panel_max"] = _panel_max_bucket()
    _load_options()
    if config.SIM_FEED and config.SIM_FEED_WARMUP:
        try:                            # история к SIM_START (без заглядывания вперёд)
            wst = _get_feed().ingest_until(_state["bucket"] - 1)
            log.info("stream feed: прогрев до старта — принято %s строк, кэш %s строк",
                     wst.get("rows_due"), wst.get("cache_rows"))
        except Exception:  # noqa: BLE001
            log.exception("stream feed warmup failed")
    log.info("sim-clock started: bucket=%s (%s), panel_max=%s (%s), tick=%ss, loop=%s, "
             "fast_factors=%s, parallel=%s",
             _state["bucket"], ts_of(_state["bucket"]), _state["panel_max"],
             ts_of(_state["panel_max"]), _state["tick_sec"], config.SIM_LOOP,
             _state["fast"], _state["parallel"])

    while not _stop.is_set():
        if _state["paused"] and _state["step_budget"] is None:
            _state["next_tick"] = None
            if _sleep(1.0):
                break
            continue
        _state["computing"] = True
        t0 = time.time()
        try:
            _db = SessionLocal()
            counts: dict = {}
            if config.SIM_FEED:
                try:                       # данные «пришли» на этот бакет
                    fst = _get_feed().ingest_until(_state["bucket"])
                    counts.update({"feed_rows": fst.get("rows_due"),
                                   "feed_cache_rows": fst.get("cache_rows"),
                                   "feed_sec": fst.get("last_sec")})
                except Exception:  # noqa: BLE001
                    log.exception("stream feed failed")
            counts.update(_compute_bucket(_state["bucket"]))
            _settings_set(_db, "sim_bucket", _state["bucket"])
            if config.AUTO_TICKETS:
                try:
                    from ..services import maintenance_service
                    res = maintenance_service.auto_generate(_db)
                    counts["tickets"] = res["created"]
                except Exception:  # noqa: BLE001
                    log.exception("auto tickets failed")
            if config.ALERTS_PUSH:
                try:
                    from . import alerts as alerts_worker
                    ar = alerts_worker.run(_db)
                    counts["alerts"] = ar.get("fired")
                    counts["pushed"] = ar.get("pushed")
                except Exception:  # noqa: BLE001
                    log.exception("alerts rule failed")
            log.info("tick bucket=%s (%s) done in %.1fs: %s", _state["bucket"],
                     ts_of(_state["bucket"]), time.time() - t0, counts)
            _state["last_counts"] = counts
            _state["last_tick"] = time.time()
            _state["last_tick_sec"] = round(time.time() - t0, 1)
            _state["error"] = None
        except Exception as exc:  # noqa: BLE001
            log.exception("tick failed")
            _state["error"] = str(exc)
        finally:
            if _db is not None:
                _db.close()
                _db = None
            _state["computing"] = False

        # ручной шаг из UI/API: сразу следующий бакет, без ожидания тика
        if _state["step_budget"] is not None:
            _state["step_budget"] -= 1
            if _state["step_budget"] <= 0:
                _state["step_budget"] = None
                _state["paused"] = _state["step_restore_paused"]
                _state["step_restore_paused"] = False
            if _state["bucket"] >= _state["panel_max"]:
                if config.SIM_LOOP:
                    _restart_replay()
                else:
                    _state["next_tick"] = None
            else:
                _state["bucket"] += 1
            continue

        if _state["bucket"] >= _state["panel_max"]:
            if not config.SIM_LOOP:
                _state["next_tick"] = None
                if _sleep(60):      # данные реплея закончились — idle
                    break
                continue
            _restart_replay()       # конец периода: цикл с января
            continue

        _state["next_tick"] = time.time() + _state["tick_sec"]
        if _sleep(max(1.0, _state["tick_sec"] - (time.time() - t0))):
            break
        _state["bucket"] += 1


def _now_ts() -> str:
    """Текущее сим-время строкой (или «—», если цикл ещё не инициализирован)."""
    b = _state["bucket"]
    return ts_of(b) if b is not None else "—"


# --- параметры прокрута (скорость демо) ---------------------------------------
SPEED_LEVELS = {1: 75, 2: 40, 4: 20, 8: 10}     # уровень -> интервал тика, сек


def _load_options() -> None:
    """Восстанавливает скорость прокрута из settings (переживает рестарт)."""
    db = SessionLocal()
    try:
        opts = _settings_get(db, "sim_options") or {}
    except Exception:  # noqa: BLE001
        opts = {}
    finally:
        db.close()
    if isinstance(opts, dict):
        if opts.get("tick_sec"):
            _state["tick_sec"] = int(opts["tick_sec"])
        _state["fast"] = bool(opts.get("fast", _state["fast"]))
        _state["parallel"] = bool(opts.get("parallel", _state["parallel"]))


def _save_options() -> None:
    db = SessionLocal()
    try:
        _settings_set(db, "sim_options", {"tick_sec": _state["tick_sec"],
                                          "fast": _state["fast"],
                                          "parallel": _state["parallel"]})
    except Exception:  # noqa: BLE001
        log.exception("не удалось сохранить sim_options")
    finally:
        db.close()


def set_speed(tick_sec: int | None = None, fast: bool | None = None,
              parallel: bool | None = None) -> dict:
    """Скорость демо-прокрута: интервал тика, отказ от SHAP и параллельный расчёт."""
    if tick_sec is not None:
        _state["tick_sec"] = max(1, min(3600, int(tick_sec)))
    if fast is not None:
        _state["fast"] = bool(fast)
    if parallel is not None:
        _state["parallel"] = bool(parallel)
    _save_options()
    _wake.set()      # применим новый интервал немедленно
    log.info("sim-clock speed: tick=%ss, fast_factors=%s, parallel=%s",
             _state["tick_sec"], _state["fast"], _state["parallel"])
    return clock_status()


def set_speed_level(level: int, fast: bool | None = None,
                    parallel: bool | None = None) -> dict:
    """Уровень демо-скорости 1×/2×/4×/8× (см. SPEED_LEVELS)."""
    lv = int(level)
    if lv not in SPEED_LEVELS:
        lv = min(SPEED_LEVELS, key=lambda k: abs(k - lv))
    return set_speed(tick_sec=SPEED_LEVELS[lv], fast=fast, parallel=parallel)


def speed_level() -> int:
    """Ближайший настроенный уровень скорости (1/2/4/8) для интервала тика."""
    tick = _state["tick_sec"] or SPEED_LEVELS[1]
    return min(SPEED_LEVELS, key=lambda k: abs(SPEED_LEVELS[k] - tick))


def _sleep(sec: float) -> bool:
    """Пауза цикла: прерывается досрочно по сигналу (_wake). True — пора останавливаться."""
    _wake.wait(max(0.05, sec))
    _wake.clear()
    return _stop.is_set()


def _restart_replay() -> int:
    """Новый круг реплея: пересчёт прогнозов с SIM_START.

    Решения диспетчера, заявки, которых коснулся человек, и журнал аудита сохраняются
    (см. `_fresh_start`) — удаляются только прогнозы и необработанные предложения модели.
    """
    global _db
    db = SessionLocal()
    try:
        b = _fresh_start(db)
    finally:
        db.close()
    if config.SIM_FEED:
        _reset_feed()                  # новый круг: журнал подаётся заново
    _state["bucket"] = int(b)
    _state["last_counts"] = None
    _state["error"] = None
    log.info("replay cycle finished — restart from %s (%s), loop=%s",
             b, ts_of(b), config.SIM_LOOP)
    return int(b)


def reset() -> dict:
    """Перезапустить реплей с 01.01.2026: пересчёт прогнозов, человеческие данные остаются."""
    _state["paused"] = False
    _state["step_budget"] = None
    _state["step_restore_paused"] = False
    _restart_replay()
    _wake.set()
    return clock_status()


def pause() -> dict:
    """Приостановить продвижение сим-времени (прогнозы больше не пересчитываются)."""
    _state["paused"] = True
    _state["step_budget"] = None
    _wake.set()
    log.info("sim-clock paused at bucket=%s (%s)", _state["bucket"], _now_ts())
    return clock_status()


def resume() -> dict:
    _state["paused"] = False
    _wake.set()
    log.info("sim-clock resumed at bucket=%s (%s)", _state["bucket"], _now_ts())
    return clock_status()


def step(n: int = 1) -> dict:
    """Просчитать n бакетов вперёд немедленно (независимо от паузы)."""
    n = max(1, min(50, int(n)))
    _state["step_restore_paused"] = _state["paused"]
    _state["paused"] = False
    _state["step_budget"] = n
    _wake.set()
    log.info("sim-clock step requested: %s бакет(ов) от %s", n, _now_ts())
    return clock_status()


def _safeloop() -> None:
    """Обёртка: падение цикла фиксируется в state (видно в /meta/clock)."""
    try:
        _loop()
    except Exception:  # noqa: BLE001
        import traceback
        _state["error"] = "".join(traceback.format_exc())[-1500:]
        _state["running"] = False
        log.exception("sim-clock loop died")


def start() -> None:
    global _thread
    if _state["running"]:
        return
    _state["running"] = True
    _stop.clear()
    _thread = threading.Thread(target=_safeloop, name="sim-clock", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
    _wake.set()
    _state["running"] = False


def clock_status() -> dict:
    b = _state["bucket"]
    start = bucket_of(dt.datetime.fromisoformat(config.SIM_START))
    total = max(1, (_state["panel_max"] or start) - start)
    # фактический темп: пауза между тиками = max(интервал, длительность расчёта)
    eff = max(float(_state["tick_sec"] or 75), float(_state["last_tick_sec"] or 0)) or 75.0
    # состояние живой подачи (SIM_FEED=1)
    if config.SIM_FEED:
        if _feed is not None:
            feed = {"enabled": True, "source": str(_feed.adapter.source),
                    "cache_dir": str(config.RAW_DIR), "panel_dir": str(config.PANEL_DIR),
                    "rows_due": _feed.stats["rows_due"], "rows_read": _feed.stats["rows_read"],
                    "cache_rows": _feed.stats["cache_rows"], "max_ts": _feed.stats["max_ts"],
                    "last_sec": _feed.stats["last_sec"], "eof": _feed.stats["eof"],
                    "chunksize": _feed.chunksize}
        else:
            feed = {"enabled": True, "source": str(config.STREAM_SOURCE),
                    "cache_dir": str(config.RAW_DIR), "panel_dir": str(config.PANEL_DIR)}
    else:
        feed = {"enabled": False}
    return {
        "mode": "replay-2026",
        "sim_now": ts_of(b) if b is not None else None,
        "bucket": b,
        "bucket_start": start,
        "start_ts": ts_of(start),
        "loop": config.SIM_LOOP,
        "paused": _state["paused"],
        "progress": round(max(0.0, min(1.0, ((b or start) - start) / total)), 4),
        "panel_max": _state["panel_max"],
        "panel_max_ts": ts_of(_state["panel_max"]) if _state["panel_max"] else None,
        "tick_sec": _state["tick_sec"],
        "speed": speed_level(),
        "fast": _state["fast"],
        "parallel": _state["parallel"],
        "last_tick_sec": _state["last_tick_sec"],
        "shap_top_k": config.SHAP_TOP_K,
        # сколько 6ч-бакетов в час реального времени и сколько идёт полный проход
        "buckets_per_hour": round(3600 / eff, 1),
        "full_pass_hours": round(total * eff / 3600, 2),
        "effective_tick_sec": round(eff, 1),
        "next_tick_in_sec": (max(0, int(_state["next_tick"] - time.time()))
                             if _state["next_tick"] else None),
        "computing": _state["computing"],
        "last_counts": _state["last_counts"],
        "error": _state["error"],
        "feed": feed,
    }
