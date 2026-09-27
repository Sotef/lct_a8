# -*- coding: utf-8 -*-
"""Инференс-контракт для backend (единая точка: модель + калибровка + топ-K).

Соглашение (ML_PLAN.md (Часть II) §19, §20 P0 «Inference-контракт»):
  - P(событие <= 24ч) = p24  — ВСЕГДА raw (калибровать бессмысленно:
    базы 0.3–1.5%, isotonic «схлопывает» хвосты; проверено notebook 26);
  - P(событие <= 30д) = risk30 — калибруется per-bin ТОЛЬКО для access и sensor
    (models/calib30_<task>.pkl); для fire — raw (val/holdout не переносятся);
  - операционная точка: топ-K по КАЛИБРОВАННОМУ risk30 (access/sensor) или по
    p24 (fire); атрибуция объёмов диспетчеру — по калиброванным вероятностям;
  - exp_days = RMST (ожидаемые дни до события в горизонте 30д) — для планов.

Вход inference: DataFrame-строки 6ч-панели (канал x бакет) с теми же
фичами, что использовались при обучении (tte_pipeline.subject_features).
Сборка панели — features.make_subdaily_panel / rebuild_task_panels.py.

Функции:
  TASKS / list_tasks() -> метаданные задачи (событие, файлы);
  load_model(task) -> CatBoostClassifier (discrete hazard);
  load_calibration(task) -> (bin_edges, rates) | None;
  is_calibrated(task) -> bool;
  predict_risk(model, subjects) -> DataFrame[p24, risk30, exp_days];
  calibrated_risk(task, risk30) -> risk30_cal (или raw, если нет калибратора);
  top_k(df, score, k) -> (hits, precision, recall, total_events);
  operational_points(task, df, ...) -> таблица топ-K операционных точек;
  oe_table / ece — калибровочные сводки (O/E, ECE);
  final_metrics() -> сводная таблица метрик по holdout-предсказаниям;
  risk_drift_by_quarter(task) -> процентили p24/risk30 по кварталам (P1 drift).

Запуск (из research/):
    .venv\\Scripts\\python.exe inference_contract.py --table   # финальная таблица
    .venv\\Scripts\\python.exe inference_contract.py --topk    # топ-K по задачам
"""
from __future__ import annotations

import pathlib
import pickle

import numpy as np
import pandas as pd

import data_utils as du
import tte_pipeline as tte

HERE = pathlib.Path(__file__).resolve().parent
MODELS = HERE / "models"
DATASET = du.find_dataset_dir()

# Метаданные задач: событие и артефакты (имена файлов совпадают с task_tte.py)
TASKS = {
    "fire": {
        "desc": "Пожарный риск: серьёзная тревога (подтв. дым >=2 ИПР / ручной, окно 6ч)",
        "panel": "subdaily_panel_fire6h.csv",
        "event_col": "серьёзных",
        "calibrated": False,   # risk30 raw (§19)
    },
    "access": {
        "desc": "Несанкционированный доступ: серия охранных тревог (proxy)",
        "panel": "subdaily_panel_access6h.csv",
        "event_col": "тревог",
        "calibrated": True,    # risk30 калибруется per-bin
    },
    "sensor": {
        "desc": "Отказ датчика: серия неисправностей (любой статус)",
        "panel": "subdaily_panel_sensor6h.csv",
        "event_col": "неисправностей",
        # §21.9: per-bin калибровка риск30 для sensor ОТКЛОНЕНА — сырые вероятности
        # уже хорошо откалиброваны на holdout (ECE 0.0155, O/E 0.91), а любой
        # per-bin по малой val (3971 субъектов) ломает holdout (ECE 0.036–0.49).
        "calibrated": False,
    },
    "wear": {
        "desc": "Износ инфраструктуры: старт серии неисправностей насосов/вент/фаз",
        "panel": "subdaily_panel_wear_6h.csv",
        "event_col": "неисправностей",
        "calibrated": False,   # risk30 raw (калибровка risk30 wear — P2, §20-4)
    },
}


def list_tasks():
    return {k: {kk: vv for kk, vv in v.items()} for k, v in TASKS.items()}


def task_paths(task: str) -> dict:
    """Пути артефактов задачи (модель, holdout-предсказания, отчёт, калибратор)."""
    return {
        "model": MODELS / f"tte_{task}_discrete_hazard.cbm",
        "holdout": MODELS / f"tte_{task}_holdout.parquet",
        "report": MODELS / f"tte_{task}_report.txt",
        "calib": MODELS / f"calib30_{task}.pkl",
        "subjects": DATASET / f"tte_subjects_{task}.parquet",
    }


def load_model(task: str):
    """Загружает CatBoost discrete-hazard модель (task_type=CPU для инференса)."""
    from catboost import CatBoostClassifier
    p = task_paths(task)["model"]
    if not p.exists():
        raise FileNotFoundError(f"модель не найдена: {p}")
    m = CatBoostClassifier(task_type="CPU")
    m.load_model(str(p))
    return m


def load_calibration(task: str):
    """Загружает per-bin калибратор risk30: (bin_edges, rates) | None."""
    fp = task_paths(task)["calib"]
    if not fp.exists():
        return None
    with open(fp, "rb") as f:
        return pickle.load(f)


def is_calibrated(task: str) -> bool:
    return TASKS[task]["calibrated"] and load_calibration(task) is not None


def apply_bin_map(cal, p):
    """Per-bin калибровка (границы, частота наблюдённого риска в бине)."""
    if cal is None:
        return p
    xq, rates = cal
    idx = np.asarray(np.searchsorted(xq, np.asarray(p, dtype=np.float64),
                                     side="right") - 1)
    return np.clip(rates[np.clip(idx, 0, len(rates) - 1).astype(int)], 0.0, 1.0)


def calibrated_risk(task: str, risk30) -> np.ndarray:
    """risk30 после per-bin калибровки (для access/sensor); для fire — raw."""
    return apply_bin_map(load_calibration(task) if TASKS[task]["calibrated"] else None,
                         np.asarray(risk30, dtype=np.float64))


def predict_risk(model, subjects: pd.DataFrame) -> pd.DataFrame:
    """Кривая выживаемости на 6ч-сетке 30д + производные.

    Требование: subjects — строки панели с колонками как при обучении
    (tte_pipeline.subject_features; целевые/служебные колонки игнорируются).
    Возвращает DataFrame: p24, risk30, exp_days (RMST, дни).
    """
    X_cols = tte.subject_features(subjects)
    X_pt, _ = tte.expand_person_time(subjects, X_cols, tte.HORIZON_BUCKETS,
                                     fixed_horizon=True)
    h = model.predict_proba(X_pt)[:, 1]
    n = len(subjects)
    S = np.cumprod(1.0 - h.reshape(n, tte.HORIZON_BUCKETS), axis=1)
    step24 = int(round(1.0 * tte.STEPS_PER_DAY)) - 1
    return pd.DataFrame({
        "p24": 1.0 - S[:, step24],
        "risk30": 1.0 - S[:, -1],
        "exp_days": S.sum(axis=1) / tte.STEPS_PER_DAY,  # RMST, дни
    })


# ---------------------------------------------------------------------------
# Топ-K операционная точка
# ---------------------------------------------------------------------------
def top_k(df: pd.DataFrame, score_col: str, k: int, y24: np.ndarray | None = None):
    """Precision/Recall топ-K по score_col.

    y24 — бинарная метка «событие в 24ч» (если None — из event_flag/obs_days).
    Возвращает dict(K, precision, recall, hits, total).
    """
    if y24 is None:
        y24 = ((df["event_flag"] == 1) & (df["obs_days"] <= 1.01)).to_numpy(int)
    order = np.argsort(-df[score_col].to_numpy())
    ys = y24[order]
    k = min(k, len(ys))
    hits = int(ys[:k].sum())
    total = int(ys.sum())
    return {"K": k, "precision": hits / k if k else np.nan,
            "recall": hits / total if total else np.nan,
            "hits": hits, "total": total}


def best_k_precision(df: pd.DataFrame, score_col: str, y24: np.ndarray,
                     min_precision: float = 0.7, max_k: int = 20_000):
    """Максимальное K с precision >= min_precision (как notebook 19)."""
    order = np.argsort(-df[score_col].to_numpy())
    ys = y24[order]
    cum = np.cumsum(ys)
    total = cum[-1]
    best = None
    for k in range(1, min(len(ys), max_k) + 1):
        p = cum[k - 1] / k
        if p >= min_precision:
            best = k
        else:
            break
    if best is None:
        return None
    k = best
    return {"K": k, "precision": cum[k - 1] / k,
            "recall": cum[k - 1] / total if total else np.nan,
            "hits": int(cum[k - 1]), "total": int(total)}


def operational_points(task: str, df: pd.DataFrame | None = None,
                       ks=(50, 100, 200, 500, 1000, 2000)) -> pd.DataFrame:
    """Таблица топ-K по p24 (24ч-прецизия) для holdout-предсказаний задачи."""
    if df is None:
        fp = task_paths(task)["holdout"]
        if not fp.exists():
            raise FileNotFoundError(fp)
        df = pd.read_parquet(fp)
    y24 = ((df["event_flag"] == 1) & (df["obs_days"] <= 1.01)).to_numpy(int)
    rows = []
    for k in ks:
        rows.append(top_k(df, "p24", k, y24))
    bk = best_k_precision(df, "p24", y24, min_precision=0.7)
    if bk:
        rows.append({"K": "max@prec>=.7", **{k2: v for k2, v in bk.items()
                                             if k2 != "K"}})
    else:
        rows.append({"K": "max@prec>=.7", "precision": np.nan, "recall": np.nan,
                     "hits": 0, "total": int(y24.sum())})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Калибровочные сводки (O/E, ECE) — как notebook 26
# ---------------------------------------------------------------------------
def oe_table(p, y, bins=10):
    p = np.asarray(p, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    idx = np.argsort(p)
    n = len(p)
    rows = []
    for i in range(bins):
        sl = idx[i * n // bins:(i + 1) * n // bins]
        pred = p[sl].mean()
        obs = y[sl].mean()
        rows.append({"pred": pred, "obs": obs, "oe": obs / pred if pred > 0 else np.nan,
                     "n": len(sl)})
    return pd.DataFrame(rows)


def ece(p, y, bins=10):
    p = np.asarray(p, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    idx = np.argsort(p)
    n = len(p)
    acc = 0.0
    for i in range(bins):
        sl = idx[i * n // bins:(i + 1) * n // bins]
        acc += abs(p[sl].mean() - y[sl].mean()) * len(sl) / n
    return acc


# ---------------------------------------------------------------------------
# Финальная таблица метрик (P0: «финальная таблица метрик»)
# ---------------------------------------------------------------------------
def _read_report_uno(task: str):
    """Uno-C / meanAUC / IBS из сохранённого отчёта task_tte.py (или NaN)."""
    import re
    fp = task_paths(task)["report"]
    if not fp.exists():
        return {"uno_c": np.nan, "mean_auc": np.nan, "ibs": np.nan,
                "km_uno_c": np.nan}
    txt = fp.read_text(encoding="utf-8")
    out = {"uno_c": np.nan, "mean_auc": np.nan, "ibs": np.nan,
           "km_uno_c": np.nan}
    for line in txt.splitlines():
        if "Uno-C=" in line and "KM-якорь" in line:
            for key, pat in (("uno_c", r"Uno-C=([\d.]+)"),
                             ("mean_auc", r"meanAUC=([\d.]+)"),
                             ("ibs", r"IBS=([\d.]+)"),
                             ("km_uno_c", r"KM-якорь: Uno-C=([\d.]+)")):
                m = re.search(pat, line)
                if m:
                    out[key] = float(m.group(1))
    return out


def final_metrics(tasks=None) -> pd.DataFrame:
    """Сводная таблица метрик по holdout-предсказаниям (без повторного обучения).

    Колонки: база24, PR-AUC(24ч), prec@50, prec@100, recall@2000, K@prec>=.7,
             ECE(risk30 raw), ECE(risk30 calib), медиана exp_days, n_holdout,
             Uno-C / IBS (из отчёта).
    """
    from tte_experiments import pr_at_horizon
    tasks = tasks or list(TASKS)
    rows = []
    for task in tasks:
        fp = pathlib.Path(MODELS) / f"tte_{task}_holdout.parquet"
        if not fp.exists():
            continue
        df = pd.read_parquet(fp)
        y24 = ((df["event_flag"] == 1) & (df["obs_days"] <= 1.01)).to_numpy(int)
        y30 = ((df["event_flag"] == 1) & (df["obs_days"] <= 30.01)).to_numpy(int)
        pr = pr_at_horizon(y24, df["p24"].to_numpy())
        r30 = df["risk30"].to_numpy(np.float64)
        r30c = calibrated_risk(task, r30)
        rep = _read_report_uno(task)
        bk = best_k_precision(df, "p24", y24, min_precision=0.7)
        if TASKS[task]["calibrated"] and load_calibration(task) is not None:
            ece_c = ece(r30c, y30)
        else:
            ece_c = np.nan
        rows.append({
            "task": task,
            "n_holdout": len(df),
            "base24": float(y24.mean()),
            "pr_auc_24": pr["pr_auc"],
            "prec@50": top_k(df, "p24", 50, y24)["precision"],
            "prec@100": top_k(df, "p24", 100, y24)["precision"],
            "recall@2000": top_k(df, "p24", 2000, y24)["recall"],
            "K@prec>=.7(24h)": bk["K"] if bk else np.nan,
            "ece_risk30_raw": ece(r30, y30),
            "ece_risk30_cal": ece_c,
            "median_exp_days": float(df["exp_days"].median()),
            "uno_c": rep["uno_c"],
            "ibs": rep["ibs"],
            "km_uno_c": rep["km_uno_c"],
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Drift-мониторинг (P1): процентили p24/risk30 по кварталам holdout
# ---------------------------------------------------------------------------
def risk_drift_by_quarter(task: str, df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Процентили p24/risk30(raw/cal) holdout-предсказаний по кварталам.

    Для прод-мониторинга: системное смещение вероятностей в квартале -> признак
    дрейфа -> пересчёт модели/калибратора.
    """
    if df is None:
        fp = task_paths(task)["holdout"]
        if not fp.exists():
            raise FileNotFoundError(fp)
        df = pd.read_parquet(fp)
    d = pd.to_datetime(df["дата"] if "дата" in df.columns else df["бакет"])
    out = df[["p24", "risk30"]].copy()
    out["квартал"] = d.dt.to_period("Q").astype(str)
    out["risk30_cal"] = calibrated_risk(task, df["risk30"].to_numpy(np.float64))
    g = (out.groupby("квартал")[["p24", "risk30", "risk30_cal"]]
         .agg(["mean", "median", lambda s: np.percentile(s, 95)]))
    g.columns = ["_".join(c).replace("<lambda_0>", "p95") for c in g.columns]
    return g.reset_index()


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", action="store_true", help="финальная таблица метрик")
    ap.add_argument("--topk", action="store_true", help="топ-K по задачам")
    a = ap.parse_args()
    if a.table:
        print(final_metrics().round(4).to_string(index=False))
    if a.topk:
        for task in TASKS:
            print(f"\n=== {task} ===")
            print(operational_points(task).round(4).to_string(index=False))


# ---------------------------------------------------------------------------
# RBAM (Фаза A, ML_PLAN.md (Часть III)): последствия + приоритет + план ТО
# ---------------------------------------------------------------------------
SEVERITY_BY_TYPE = {
    # (тип_датчика) -> вес последствия [0..1], см. research/docs/SEVERITY_MAP.md
    "Ручной извещатель": 0.95,
    "Датчик дыма": 0.85,
    "Газовый датчик": 0.80,
    "Состояние насоса": 0.80,
    "Датчик затопления": 0.75,
    "КД Люк": 0.70,
    "9-секционный люк": 0.70,
    "Тепловой датчик": 0.65,
    "КД Дверь": 0.60,
    "КД АВ": 0.60,
    "Стекло": 0.60,
    "Состояние вентилятора": 0.60,
    "Датчик температуры": 0.55,
    "Датчик движения": 0.55,
    "Состояние фазы": 0.50,
}
DEFAULT_SEVERITY = 0.35


def severity_of(channel_type: str) -> float:
    """Вес последствия по типу канала (эвристика v1, SEVERITY_MAP.md)."""
    return SEVERITY_BY_TYPE.get(str(channel_type), DEFAULT_SEVERITY)


def scale_of(n_channels_30d) -> float:
    """Масштаб объекта по числу активных каналов за 30д (прокси без реестра)."""
    try:
        n = float(n_channels_30d)
    except (TypeError, ValueError):
        n = 0.0
    if n > 20:
        return 1.5
    if 6 <= n <= 20:
        return 1.25
    return 1.0


def plan_bucket(exp_days: float) -> str:
    """Желаемый горизонт ТО по exp_days (мягкие границы)."""
    try:
        d = float(exp_days)
    except (TypeError, ValueError):
        return "плановый"
    if d < 7:
        return "текущий квартал"
    if d < 21:
        return "следующий квартал"
    return "плановый год"


def rbam_view(task: str, df: pd.DataFrame | None = None,
              k: int = 500, with_columns: list[str] | None = None) -> pd.DataFrame:
    """Риск-портфель RBAM: риск × последствие × масштаб (Фаза A).

    Берёт holdout-предсказания задачи, добавляет severity/scale/score и
    сортирует по score desc. Канал с активным событием помечается отдельно.
    """
    if df is None:
        fp = task_paths(task)["holdout"]
        if not fp.exists():
            raise FileNotFoundError(fp)
        df = pd.read_parquet(fp)
    out = df.copy()
    r = out["risk30"].to_numpy(np.float64)
    out["risk30_cal"] = calibrated_risk(task, r)
    out["risk_used"] = out["risk30_cal"]
    out["severity"] = out["тип_датчика"].map(severity_of)
    # масштаб объекта: если панель-колонка недоступна, берём 1.0
    if "каналов_активных_об_б_сум_30д" in out.columns:
        out["scale"] = out["каналов_активных_об_б_сум_30д"].map(scale_of)
    else:
        out["scale"] = 1.0
    out["score"] = out["risk_used"] * out["severity"] * out["scale"]
    out["plan"] = out["exp_days"].map(plan_bucket)
    out = out.sort_values("score", ascending=False).reset_index(drop=True)
    cols = ["ид_канала_данных", "бакет", "дата", "тип_датчика",
            "severity", "scale", "p24", "risk30", "risk_used", "exp_days",
            "score", "plan", "event_flag", "obs_days"]
    if with_columns:
        cols = cols + [c for c in with_columns if c in out.columns and c not in cols]
    return out[cols].head(k).reset_index(drop=True)


def top_risks(task: str, k: int = 200, active_only: bool = False) -> dict:
    """JSON-контракт для GET /top-risks (Фаза B)."""
    v = rbam_view(task, k=k)
    if active_only:
        v = v[(v["event_flag"] == 1) & (v["obs_days"] <= 30.01)]
    rec = v.to_dict(orient="records")
    for row in rec:
        for key in ("severity", "scale", "p24", "risk30", "risk_used",
                    "exp_days", "score"):
            row[key] = float(row[key])
        row["бакет"] = int(row["бакет"])
        row["event_flag"] = int(row["event_flag"])
        row["obs_days"] = float(row["obs_days"])
    return {"task": task, "k": len(rec), "items": rec}


def maintenance_plan(task: str, k: int = 1000) -> dict:
    """JSON-контракт для GET /maintenance-plan: агрегат по (plan, тип)."""
    v = rbam_view(task, k=k)
    agg = (v.groupby(["plan", "тип_датчика"])
           .agg(каналов=("ид_канала_данных", "count"),
                риск_средний=("risk_used", "mean"),
                score_сумма=("score", "sum"),
                exp_days_медиана=("exp_days", "median"))
           .reset_index())
    for col in ("риск_средний", "score_сумма", "exp_days_медиана"):
        agg[col] = agg[col].round(4)
    return {"task": task, "rows": agg.to_dict(orient="records")}


if __name__ == "__main__":
    main()