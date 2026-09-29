# -*- coding: utf-8 -*-
"""Оркестрация: данные -> панель -> субъекты -> инференс -> прогнозы в БД.

Фоновый воркер (workers/scheduler) вызывает compute_and_store_bucket() каждые 6ч;
ручной запуск — POST /admin/data/load.
"""
from __future__ import annotations

import datetime as dt
import json
import logging

import numpy as np
import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import task_cfg
from .. import config
from .. import models_db as dbm
from ..adapters.journal import bucket_to_timestamp
from . import feature_pipeline as fp
from . import incident_log
from . import inference as inf
from . import ml_registry
from .alarm_service import alarm_class as _alarm_class

log = logging.getLogger("prediction")


def _bucket_ts(bucket: int) -> dt.datetime:
    ts = pd.Timestamp(bucket_to_timestamp(bucket))
    return ts.to_pydatetime()


def _f(v):
    try:
        f = float(v)
        return None if np.isnan(f) else round(f, 6)
    except (TypeError, ValueError):
        return None


def _dtv(v):
    """Значение -> datetime или None (для norm_due/plan_date)."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return pd.Timestamp(v).to_pydatetime()
    except (TypeError, ValueError):
        return None


def features_slice(subject_row: pd.Series, task: str) -> dict:
    """JSON-срез фич канала (карточка «факторы», без служебных колонок)."""
    cols = ml_registry.get(task)["feature_cols"]
    data = {}
    for c in cols:
        v = subject_row.get(c)
        if v is None:
            data[c] = None
        elif isinstance(v, (np.floating, float)):
            data[c] = None if (isinstance(v, float) and np.isnan(v)) else round(float(v), 5)
        elif isinstance(v, (np.integer, int)):
            data[c] = int(v)
        else:
            data[c] = None if pd.isna(v) else float(v)
    return data
def compute_and_store_bucket(task: str, bucket: int, db: Session,
                             model_holder: dict,
                             recompute_panel: bool = False,
                             subjects: pd.DataFrame | None = None,
                             with_factors: bool = True) -> dict:
    """Прогноз для ВСЕХ активных каналов задачи на заданном бакете + запись в БД.

    Идемпотентно: старые прогнозы на бакет удаляются, записываются свежие.
    `subjects` — готовые субъекты (одна сборка на много бакетов, см. run_replay).
    `with_factors=False` — экономит SHAP (массовый пересчёт истории).
    """
    if subjects is None:
        subjects = fp.build_subjects(task, recompute_panel=recompute_panel)
    bucket_rows = fp.subjects_for_bucket(subjects, bucket)
    if not len(bucket_rows):
        return {"task": task, "bucket": bucket,
                "bucket_ts": str(_bucket_ts(bucket)),
                "n_subjects": 0, "n_stored": 0}

    version = (model_holder.get(task) or {}).get("model_version", "unknown")

    # Пересчёт бакета: старые прогнозы удаляются. Сначала отвязываем от них заявки —
    # maintenance_tasks.prediction_id ссылается на predictions.id (FK), и без этого
    # DELETE падает на бакетах, где автоформирование уже создало заявку (в реплее это
    # случается при повторном проходе бакета или сбросе круга).
    old_ids = (db.query(dbm.Prediction.id)
               .filter(dbm.Prediction.task == task,
                       dbm.Prediction.bucket_ts == _bucket_ts(bucket),
                       dbm.current_only()))
    (db.query(dbm.MaintenanceTask)
     .filter(dbm.MaintenanceTask.prediction_id.in_(old_ids))
     .update({"prediction_id": None}, synchronize_session=False))
    db.query(dbm.Prediction).filter(
        dbm.Prediction.task == task,
        dbm.Prediction.bucket_ts == _bucket_ts(bucket),
        dbm.current_only()).delete(synchronize_session=False)
    # ВАЖНО: коммит сразу — иначе write-lock SQLite держится весь долгий
    # инференс и параллельные записи (audit_log при логине и т.п.) падают
    # с "database is locked".
    db.commit()

    rb = inf.rbam_frame(task, bucket_rows)
    S = inf.predict_survival_curve(task, bucket_rows)
    surv_pts = inf.surv_points_from(S)
    # P(событие ≤ 72ч) = 1 - S(12-й 6ч-бакет); выровнено с bucket_rows (до сортировки)
    p72_all = (1.0 - S[:, 11]) if (S.ndim == 2 and S.shape[1] > 11) else None
    # P(событие ≤ 7 дней): 28-й шаг 6ч-сетки (7*4), индекс 27
    p7d_all = (1.0 - S[:, 27]) if (S.ndim == 2 and S.shape[1] > 27) else None

    # SHAP: только топ-N по score (карточки верхних рисков всегда с факторами).
    # SHAP — самое дорогое место тика (~43 с на задачу при N=400); SHAP_TOP_K
    # позволяет ускорить пересчёт, оставив факторы для верхушки списка.
    shap_map: dict = {}
    if with_factors and len(rb):
        top_orig = [int(x) for x in list(rb.index[:config.SHAP_TOP_K])]
        shap_list = shap_factors_batch(task, bucket_rows.iloc[top_orig])
        shap_map = dict(zip(top_orig, shap_list))

    rows = []
    for i, (_, row) in enumerate(rb.iterrows()):
        # rb отсортирован по score; orig — позиция строки в bucket_rows (subjects),
        # чтобы surv_points/features/факторы соответствовали своему каналу.
        orig = int(rb.index[i])
        subj = bucket_rows.iloc[orig]
        rows.append(dbm.Prediction(
            task=task,
            channel_id=str(row["ид_канала_данных"]),
            object_id=str(row["ид_объект"]),
            bucket_ts=_bucket_ts(bucket),
            p24=_f(row["p24"]),
            p72=_f(p72_all[orig]) if p72_all is not None else None,
            p7d=_f(p7d_all[orig]) if p7d_all is not None else None,
            risk30=_f(row["risk30"]),
            risk30_cal=_f(row["risk30_cal"]),
            exp_days=_f(row["exp_days"]),
            score=_f(row["score"]),
            severity=_f(row["severity"]),
            scale=_f(row["scale"]),
            plan=str(row["plan"]),
            surv_points=surv_pts[orig] if surv_pts else None,
            factors=shap_map.get(orig),
            features_json=features_slice(subj, task),
            event_flag=int(row["event_flag"]) if not pd.isna(row["event_flag"]) else 0,
            obs_days=_f(row["obs_days"]),
            age_days=_f(row.get("age_days")),
            norm_due=_dtv(row.get("norm_due")),
            plan_date=_dtv(row.get("plan_date")),
            campaign=int(row.get("campaign") or 0),
            model_version=version,
        ))
    db.add_all(rows)
    db.commit()
    # происшествия бакета — в системный лог и аудит (вкладка «Система»); дедуп по канал×бакет
    try:
        n_inc = incident_log.log_bucket(db, task, bucket, rows)
    except Exception:  # noqa: BLE001
        log.exception("не удалось залогировать происшествия бакета %s", bucket)
        n_inc = 0
    return {"task": task, "bucket": bucket,
            "bucket_ts": str(_bucket_ts(bucket)),
            "n_subjects": int(len(bucket_rows)),
            "n_stored": len(rows),
            "n_incidents_logged": n_inc}


def compute_factors_for_prediction(db: Session, pred: dbm.Prediction,
                                   top_k: int = 8) -> list[dict] | None:
    """SHAP-факторы «почему» для одного прогноза (если их не посчитали на тике).

    В быстром режиме прокрута факторы не считаются массово; здесь они считаются
    по запросу карточки: субъекты задачи берутся из панели (кэш в памяти), для
    одной строки SHAP занимает доли секунды. Результат сохраняется в прогнозе.
    """
    if pred.factors:
        return pred.factors
    subs = _subject_cache(pred.task)
    if subs is None:
        return None
    # бакет из bucket_ts: та же эпоха, что в features/bucket_of (naive -> UTC-шкала)
    bucket = int(pd.Timestamp(pred.bucket_ts).value // (6 * 3600 * 10 ** 9))
    rows = subs[(subs["бакет"] == bucket)
                & (subs["ид_канала_данных"].astype(str) == str(pred.channel_id))]
    if not len(rows):
        return None
    try:
        factors = shap_factors_batch(pred.task, rows.iloc[:1], top_k=top_k)[0]
    except Exception:  # noqa: BLE001
        log.exception("не удалось посчитать факторы для прогноза %s", pred.id)
        return None
    pred.factors = factors
    db.commit()
    return factors


_SUBJ_CACHE: dict = {}


def _subject_cache(task: str):
    """Субъекты задачи из панели (ленивая загрузка, без пересборки панели)."""
    if task not in _SUBJ_CACHE:
        try:
            _SUBJ_CACHE[task] = fp.build_subjects(task, recompute_panel=False)
        except Exception:  # noqa: BLE001
            log.exception("не удалось собрать субъекты задачи %s", task)
            return None
    return _SUBJ_CACHE[task]


def shap_factors_batch(task: str, subjects: pd.DataFrame,
                       top_k: int = 8) -> list[list[dict]]:
    """Топ-фичи «почему» (SHAP через CatBoost ShapValues), батчем по всем субъектам."""
    from ..research_bridge import module as _m
    tte = _m("tte_pipeline")
    entry = ml_registry.get(task)
    X_cols = entry["feature_cols"]
    names = list(X_cols)
    if len(subjects) == 0:
        return []
    X_pt, _ = tte.expand_person_time(subjects, X_cols, tte.HORIZON_BUCKETS,
                                     fixed_horizon=True)
    pool = _m("catboost").Pool(X_pt)
    try:
        shap = np.asarray(entry["model"].get_feature_importance(pool, type="ShapValues"))
        out = []
        for row in shap:
            pairs = sorted(zip(names, row[:len(names)]), key=lambda t: -abs(t[1]))
            out.append([{"feature": n, "shap": round(float(v), 5)}
                        for n, v in pairs[:top_k]])
        return out
    except Exception:  # noqa: BLE001
        out = []
        for _ in range(len(subjects)):
            out.append([{"feature": c, "shap": None} for c in names[:top_k]])
        return out
def _pred_to_item(p: dbm.Prediction, sensor_type=None, sensor_name=None,
                  obj=None, tag=None, system_type=None):
    sp = p.surv_points or []
    _ac = _alarm_class(sensor_type)
    p7d = p.p7d
    if p7d is None and len(sp) >= 6:
        # старые записи: колонки p7d ещё не было — считаем из S(t)
        try:
            p7d = 1.0 - float(sp[5])          # 7 дней — 6-я точка S(t)
        except (TypeError, ValueError):
            p7d = None
    return {
        "id": p.id,
        "ид_канала_данных": p.channel_id,
        "object_id": p.object_id,
        "название_объекта": getattr(obj, "name", None),
        "тип_объекта": getattr(obj, "object_type", None),
        "район": getattr(obj, "district", None),
        "бакет": int(p.bucket_ts.timestamp() // (6 * 3600)) if p.bucket_ts else None,
        "bucket_ts": p.bucket_ts.isoformat() if p.bucket_ts else None,
        "дата": str(p.bucket_ts.date()) if p.bucket_ts else None,
        "тип_датчика": sensor_type,
        "название_датчика": sensor_name,
        "тег_инж_системы": tag,
        "инж_система": system_type,
        "severity": p.severity,
        "scale": p.scale,
        # класс последствия по ответам заказчика: авария (пожар/наводнение/газ/террор/аном. темп.)
        # или инцидент (электроснабжение/связь → «слепые зоны», косвенно намекают на аварию)
        "класс_события": _ac["класс"],
        "группа_события": _ac["группа"],
        "косвенно_авария": _ac["косвенно_авария"],
        "p24": p.p24,
        "p72": p.p72,
        "p7d": round(p7d, 6) if p7d is not None else None,
        "p7d": _p7d(p.surv_points),
        "risk30": p.risk30,
        "risk30_cal": p.risk30_cal,
        "risk_used": p.risk30_cal if p.risk30_cal is not None else p.risk30,
        "exp_days": p.exp_days,
        "score": p.score,
        "plan": p.plan,
        "event_flag": p.event_flag,
        "obs_days": p.obs_days,
        # --- план ТО (см. README «План ТО: как приоритизируются заявки») ---
        "age_years": round(p.age_days / 365.25, 2) if p.age_days is not None else None,
        "norm_due": p.norm_due.isoformat() if p.norm_due else None,
        "plan_date": p.plan_date.isoformat() if p.plan_date else None,
        "campaign": int(p.campaign or 0),
    }


def _p7d(surv_points) -> float | None:
    """P(событие ≤ 7 дней) = 1 − S(7д); 7 дней — 6-я точка [6ч,12ч,24ч,48ч,3д,7д,14д,30д]."""
    try:
        if not surv_points or len(surv_points) < 6:
            return None
        return round(1.0 - float(surv_points[5]), 6)
    except (TypeError, ValueError):
        return None


def _sim_bucket_dt() -> dt.datetime | None:
    """Дата начала текущего бакета сим-часов (реплей). None — часы выключены/не готовы."""
    try:
        from ..workers import ingestion, simclock
        st = simclock.clock_status() or {}
        b = st.get("bucket")
        try:
            b = int(b)
        except (TypeError, ValueError):
            return None
        ts = ingestion._bucket_ts(b)                     # pandas.Timestamp
        return ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else dt.datetime(ts)
    except Exception:                      # noqa: BLE001 — часы не должны ломать чтение прогнозов
        return None


def latest_bucket_ts(db: Session, task: str):
    """Максимальный bucket_ts хранимых прогнозов задачи (datetime | None).

    Служебные «закреплённые» строки (метки решений, `pinned=1`) не учитываются — иначе после
    перезапуска реплея текущим считался бы бакет прошлого круга.

    В режиме реплея «актуальным» считается последний посчитанный бакет ТЕКУЩЕГО круга —
    не позже текущего сим-времени. Без этого после кнопки «Заново с января» тренд, топ-риски
    и алерты цеплялись бы за бакеты прошлого круга (дальние месяцы), и интерфейс показывал бы
    устаревшую и почти пустую картину.
    """
    base = db.query(func.max(dbm.Prediction.bucket_ts)).filter(
        dbm.Prediction.task == task, dbm.current_only())
    top = _sim_bucket_dt()
    if top is not None:
        got = base.filter(dbm.Prediction.bucket_ts <= top).scalar()
        if got is not None:
            return got
    return base.scalar()


def top_risks(task: str, k: int = 200, active_only: bool = False,
              db: Session = None, bucket: int | None = None,
              object_ids: list[str] | None = None,
              horizon: str = "30d") -> dict:
    """Топ-K RBAM из хранимых прогнозов.

    bucket=None -> актуальный (максимальный) бакет прогнозов задачи.
    horizon: 24h | 72h | 30d — сортировка по вероятности события на горизонте.
    """
    if bucket is None:
        last_ts = latest_bucket_ts(db, task)
    q = db.query(dbm.Prediction, dbm.ChannelRef.sensor_type,
                 dbm.ChannelRef.sensor_name, dbm.ChannelRef.tag,
                 dbm.ChannelRef.system_type, dbm.ObjectRef) \
        .outerjoin(dbm.ChannelRef,
                   dbm.ChannelRef.channel_id == dbm.Prediction.channel_id) \
        .outerjoin(dbm.ObjectRef,
                   dbm.ObjectRef.object_id == dbm.Prediction.object_id) \
        .filter(dbm.Prediction.task == task)
    if bucket is not None:
        q = q.filter(dbm.Prediction.bucket_ts == _bucket_ts(bucket))
    elif last_ts is not None:
        q = q.filter(dbm.Prediction.bucket_ts == last_ts)
    if object_ids is not None:
        q = q.filter(dbm.Prediction.object_id.in_(object_ids))
    if active_only:
        q = q.filter(dbm.Prediction.event_flag == 1)
    # сортировка под горизонт: 24ч/72ч — короткие горизонты (оперативная очередь),
    # 30d — RBAM-скор (планирование ТО)
    order_col = {"24h": dbm.Prediction.p24,
                 "72h": dbm.Prediction.p72}.get(horizon, dbm.Prediction.score)
    q = q.order_by(order_col.desc().nulls_last()).limit(min(k, 1000))
    fetched = q.all()
    items = [_pred_to_item(p, st, sn, obj=obj, tag=tg, system_type=sy)
             for p, st, sn, tg, sy, obj in fetched]
    sort_key = {"24h": lambda it: (it.get("p24") or 0.0),
                "72h": lambda it: (it.get("p72") or 0.0)}.get(
        horizon, lambda it: (it.get("score") or 0.0))
    items.sort(key=lambda it: -sort_key(it))
    return {"task": task, "horizon": horizon,
            "k": len(items[:k]), "items": items[:k]}


def forecasts_list(task: str, object_id: str | None = None,
                   status: str | None = None, page: int = 1, size: int = 50,
                   bucket: int | None = None, db: Session = None,
                   object_ids: list[str] | None = None,
                   horizon: str = "30d") -> dict:
    q = db.query(dbm.Prediction).filter(dbm.Prediction.task == task, dbm.current_only())
    if object_id:
        q = q.filter(dbm.Prediction.object_id == object_id)
    if object_ids is not None:
        q = q.filter(dbm.Prediction.object_id.in_(object_ids))
    if status:
        q = q.filter(dbm.Prediction.plan == status)
    if bucket is not None:
        q = q.filter(dbm.Prediction.bucket_ts == _bucket_ts(bucket))
    total = q.count()
    qj = (q.join(dbm.ChannelRef,
                 dbm.ChannelRef.channel_id == dbm.Prediction.channel_id,
                 isouter=True)
          .join(dbm.ObjectRef,
                dbm.ObjectRef.object_id == dbm.Prediction.object_id,
                isouter=True)
          .add_columns(dbm.ChannelRef.sensor_type,
                       dbm.ChannelRef.sensor_name,
                       dbm.ChannelRef.tag,
                       dbm.ChannelRef.system_type, dbm.ObjectRef))
    order_col = {"24h": dbm.Prediction.p24,
                 "72h": dbm.Prediction.p72}.get(horizon, dbm.Prediction.score)
    qj = (qj.order_by(order_col.desc().nulls_last())
          .offset((page - 1) * size).limit(size))
    items = [_pred_to_item(p, st, sn, obj=obj, tag=tg, system_type=sy)
             for p, st, sn, tg, sy, obj in qj.all()]
    sort_key = {"24h": lambda it: (it.get("p24") or 0.0),
                "72h": lambda it: (it.get("p72") or 0.0)}.get(
        horizon, lambda it: (it.get("score") or 0.0))
    items.sort(key=lambda it: -sort_key(it))
    return {"task": task, "horizon": horizon, "page": page, "size": size,
            "total": total, "items": items}


def top_objects(task: str, db: Session, k: int = 50, horizon: str = "72h",
                bucket: int | None = None,
                object_ids: list[str] | None = None) -> dict:
    """Топ-K объектов по вкладу: Σ (severity_канала × P(событие ≤ горизонт)).

    horizon: 24h -> p24, 72h -> p72, 30d -> risk30_cal/risk30.
    У каждого объекта — топ-3 канала с максимальным вкладом.
    """
    if bucket is None:
        last_ts = latest_bucket_ts(db, task)
        if last_ts is None:
            return {"task": task, "horizon": horizon, "items": []}
    pcol = {"24h": dbm.Prediction.p24,
            "72h": dbm.Prediction.p72}.get(horizon, dbm.Prediction.risk30)
    q = (db.query(dbm.Prediction, dbm.ObjectRef)
         .outerjoin(dbm.ObjectRef,
                    dbm.ObjectRef.object_id == dbm.Prediction.object_id)
         .filter(dbm.Prediction.task == task))
    if bucket is not None:
        q = q.filter(dbm.Prediction.bucket_ts == _bucket_ts(bucket))
    else:
        q = q.filter(dbm.Prediction.bucket_ts == last_ts)
    if object_ids is not None:
        q = q.filter(dbm.Prediction.object_id.in_(object_ids))
    agg: dict = {}
    for p, obj in q.all():
        ph = getattr(p, {"24h": "p24", "72h": "p72"}.get(horizon, "risk30")) \
            if horizon != "30d" else (p.risk30_cal if p.risk30_cal is not None else p.risk30)
        if ph is None:
            continue
        sev = p.severity if p.severity is not None else 0.5
        contrib = float(ph) * float(sev)
        a = agg.setdefault(p.object_id, {
            "object_id": p.object_id,
            "название_объекта": getattr(obj, "name", None),
            "тип_объекта": getattr(obj, "object_type", None),
            "район": getattr(obj, "district", None),
            "каналов": 0, "вклад": 0.0, "риск_макс": 0.0, "top_channels": [],
        })
        a["каналов"] += 1
        a["вклад"] += contrib
        a["риск_макс"] = max(a["риск_макс"], float(ph))
        a["top_channels"].append({
            "prediction_id": p.id, "channel_id": p.channel_id,
            "p_horizon": round(float(ph), 4),
            "severity": round(float(sev), 3),
            "вклад": round(contrib, 4)})
    items = sorted(agg.values(), key=lambda a: -a["вклад"])[:k]
    for a in items:
        a["вклад"] = round(a["вклад"], 4)
        a["top_channels"] = sorted(a["top_channels"],
                                   key=lambda ch: -ch["вклад"])[:3]
    return {"task": task, "horizon": horizon, "k": len(items), "items": items}


def maintenance_plan(task: str, db: Session,
                     bucket: int | None = None,
                     object_ids: list[str] | None = None) -> dict:
    """Агрегат «план ТО x тип канала» из прогнозов (bucket=None — актуальный)."""
    import statistics
    q = db.query(dbm.Prediction, dbm.ChannelRef.sensor_type) \
        .outerjoin(dbm.ChannelRef,
                   dbm.ChannelRef.channel_id == dbm.Prediction.channel_id) \
        .filter(dbm.Prediction.task == task)
    if object_ids is not None:
        q = q.filter(dbm.Prediction.object_id.in_(object_ids))
    if bucket is not None:
        q = q.filter(dbm.Prediction.bucket_ts == _bucket_ts(bucket))
    else:
        last_ts = latest_bucket_ts(db, task)
        if last_ts is not None:
            q = q.filter(dbm.Prediction.bucket_ts == last_ts)
    fetched = q.all()
    if not fetched:
        return {"task": task, "rows": []}
    agg: dict = {}
    for p, stype in fetched:
        key = (p.plan or "плановый", stype or "прочее")
        a = agg.setdefault(key, {"n": 0, "risk": 0.0, "score": 0.0,
                                 "exp": [], "age": [], "norm": []})
        a["n"] += 1
        a["risk"] += (p.risk30_cal if p.risk30_cal is not None else p.risk30) or 0.0
        a["score"] += p.score or 0.0
        a["exp"].append(p.exp_days or 0.0)
        if p.age_days is not None:
            a["age"].append(p.age_days / 365.25)
        if p.norm_due is not None and p.bucket_ts is not None:
            a["norm"].append((p.norm_due.replace(tzinfo=None)
                              - p.bucket_ts.replace(tzinfo=None)).days)
    rows = []
    for (plan, typ), a in sorted(agg.items()):
        n = a["n"]
        rows.append({"plan": plan, "тип_датчика": typ, "каналов": n,
                     "риск_средний": round(a["risk"] / n, 4),
                     "score_сумма": round(a["score"], 4),
                     "exp_days_медиана": round(statistics.median(a["exp"]), 4),
                     "возраст_лет_медиана": (round(statistics.median(a["age"]), 2)
                                             if a["age"] else None),
                     "норматив_дней_медиана": (round(statistics.median(a["norm"]), 1)
                                               if a["norm"] else None)})
    return {"task": task, "rows": rows}