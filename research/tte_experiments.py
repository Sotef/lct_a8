# -*- coding: utf-8 -*-
"""Эксперимент: survival-апгрейд слоя 2 (person-time discrete hazard + anchors).

Запуск (из research/, venv research):
    .venv\\Scripts\\python.exe tte_experiments.py --quick
    .venv\\Scripts\\python.exe tte_experiments.py            # полный прогон
    .venv\\Scripts\\python.exe tte_experiments.py --bench    # + бенчмарки (SurvivalAft, RSF)

Валидация: train <= 2024-12-31, внутренняя val 2025-01..06 (только модельный
выбор), держанный период >= 2025-07-01 НЕ используется до финальной оценки.
"""
from __future__ import annotations

import argparse
import pathlib
import time

import numpy as np
import pandas as pd

import tte_pipeline as tte


def build_dataset(cache_name: str = "tte_subjects.parquet") -> pd.DataFrame:
    """Строит (и кэширует) таблицу субъектов с цензурой. Полное отделение от val/holdout:
    z-статистики — только по train; метки — с цензурой на HOLDOUT_START."""
    cache = tte.fe.DATASET / cache_name
    if cache.exists():
        return pd.read_parquet(cache)

    t0 = time.time()
    panel = tte.load_panel()
    print(f"[data] панель: {panel.shape} ({time.time()-t0:.0f}s)")
    panel = tte.refit_z_train_only(panel)
    panel = tte.add_series_context(panel)
    subjects = tte.add_tte_labels(panel)

    # категориальные коды (как в ноутбуках 08-10)
    subjects["ид_объект_code"] = subjects["ид_объект"].astype("category").cat.codes
    subjects["тип_датчика_code"] = subjects["тип_датчика"].astype("category").cat.codes
    subjects = subjects.sort_values(["ид_канала_данных", "бакет"]).reset_index(drop=True)

    subjects.to_parquet(cache, index=False)
    print(f"[data] субъекты сохранены: {cache.name}, {subjects.shape[0]:,} строк")
    return subjects


def verify_no_lookup(train, val, holdout) -> None:
    """Ассерты честности сплита/цензуры перед обучением."""
    dt_tr = pd.to_datetime(train["дата"])
    dt_va = pd.to_datetime(val["дата"])
    dt_ho = pd.to_datetime(holdout["дата"])
    assert dt_tr.max() <= tte.TRAIN_END, "train заглядывает в будущее"
    assert dt_va.max() < tte.HOLDOUT_START, "val заглядывает в holdout"
    assert dt_ho.min() >= tte.HOLDOUT_START, "holdout смешан с val"
    # метки строк до holdout не пересекают HOLDOUT_START (цензура на границе)
    boundary = (tte.HOLDOUT_START - pd.Timestamp("1970-01-01")).days
    for name, s in (("train", train), ("val", val)):
        d0 = pd.to_datetime(s["дата"])
        assert (d0 + pd.to_timedelta(s["obs_days"], unit="D") <= tte.HOLDOUT_START).all(), \
            f"{name}: цензура пересекает holdout"
    print("[leak-check] ok: train/val <= 2025-06-30, holdout >= 2025-07-01, "
          "метки не пересекают границу")


def impute_train_median(fit_mask, X_train_pt, X_eval_pt):
    """IMPUTATION по медианам только обучающей (person-time) матрицы.
    Возвращает (X_train_f, X_eval_f) с заполненными NaN — для не-CatBoost моделей.
    Для CatBoost использовать исходные матрицы (NaN понимает нативно)."""
    med = X_train_pt.median(numeric_only=True)
    return X_train_pt.fillna(med), X_eval_pt.fillna(med)
def fit_discrete_hazard(X_tr, y_tr, X_va, y_va, iters=400, lr=0.05, depth=6, seed=42):
    """Person-time discrete hazard: CatBoost(Logloss) на развернутых строках."""
    from catboost import CatBoostClassifier, Pool
    m = CatBoostClassifier(iterations=iters, learning_rate=lr, depth=depth,
                           random_seed=seed, task_type="CPU", loss_function="Logloss",
                           eval_metric="Logloss", early_stopping_rounds=100, verbose=100)
    m.fit(Pool(X_tr, y_tr), eval_set=Pool(X_va, y_va))
    return m


def predict_survival_discrete(model, hold_subjects, X_cols):
    """S(t) для всех субъектов на сетке 6ч-бакетов (n, HORIZON_BUCKETS)."""
    X_pt, _ = tte.expand_person_time(hold_subjects, X_cols, tte.HORIZON_BUCKETS,
                                     fixed_horizon=True)
    h = model.predict_proba(X_pt)[:, 1]
    n = len(hold_subjects)
    H = h.reshape(n, tte.HORIZON_BUCKETS)
    return np.cumprod(1.0 - H, axis=1)


def _first(x):
    return x[0] if isinstance(x, tuple) else x


def survival_metrics(surv_train, surv_test, risk, S, times_days):
    """Uno-C, динамический AUC, IPCW-Brier, IBS, Brier на сетке времён.

    IPCW-оценки требуют, чтобы времена оценок были строго меньше максимума
    цензурных времён в train. Административная цензура упирается в 30 дней,
    поэтому для Brier/IBS/AUC используем сетку < 30д (учитываем до 14д).
    На вырожденных выборках метрики не считаем (NaN).
    """
    from sksurv.metrics import (brier_score, concordance_index_ipcw,
                                cumulative_dynamic_auc, integrated_brier_score)
    ok = times_days < 29.0
    times_ok = np.asarray(times_days)[ok]
    if S.shape[1] == tte.HORIZON_BUCKETS:
        # полная 6ч-сетка до 30 дней (discrete hazard)
        idx = np.clip(np.round(times_ok * tte.STEPS_PER_DAY).astype(int) - 1,
                      0, tte.HORIZON_BUCKETS - 1)
        S_ok = S[:, idx]
    else:
        # матрица уже на сетке EVAL_TIMES (якоря KM/NA и пр.)
        col_ok = np.where(ok)[0]
        S_ok = S[:, col_ok]

    try:
        c = _first(concordance_index_ipcw(surv_train, surv_test, risk, tau=29.0))
    except ValueError:
        c = float("nan")

    auc_ok = False
    aucs, mcm = np.full(4, np.nan), float("nan")
    surv_test_auc = np.copy(surv_test)
    surv_test_auc["time"] = np.minimum(surv_test_auc["time"].astype(np.float64), 29.9)
    for ts in ([2.0, 3.0, 7.0, 14.0], [1.0, 2.0, 3.0, 7.0], [0.5, 1.0, 2.0, 3.0]):
        try:
            aucs, mcm = cumulative_dynamic_auc(surv_train, surv_test_auc, risk, times=ts)
            auc_ok = True
            break
        except ValueError:
            continue

    try:
        ibs = float(integrated_brier_score(surv_train, surv_test, S_ok, times_ok))
    except ValueError:
        ibs = float("nan")
    try:
        brier = brier_score(surv_train, surv_test, S_ok, times_ok)[1]
    except ValueError:
        brier = np.full(len(times_ok), np.nan)

    return {
        "uno_c": float(c),
        "mean_auc": float(mcm) if auc_ok else float("nan"),
        "auc_by_t": dict(zip(np.round([0.5, 1.0, 2.0, 3.0] if not auc_ok else ts, 2),
                             np.round(aucs, 4))),
        "ibs": ibs,
        "brier": dict(zip(np.round(times_ok, 2), np.round(brier, 4))),
        "times_ok": times_ok.tolist(),
    }


def pick_threshold(y_bin, p_bin, min_precision: float = 0.7):
    """Наилучший порог под Precision>=min_precision (макс. recall). Возвращает (thr, p, r)."""
    from sklearn.metrics import precision_score as ps, recall_score as rs
    best = None
    for thr in np.round(np.arange(0.05, 0.99, 0.01), 3):
        yp = (p_bin >= thr).astype(int)
        p_, r_ = ps(y_bin, yp, zero_division=0), rs(y_bin, yp)
        if p_ >= min_precision and (best is None or r_ > best[2]):
            best = (float(thr), float(p_), float(r_))
    return best if best is not None else (float("nan"), float("nan"), float("nan"))


def pr_at_horizon(y_bin, p_bin):
    """Precision/Recall на бинарной цели (событие в горизонт) + PR-AUC + порог P>=0.7."""
    from sklearn.metrics import (average_precision_score, precision_recall_curve,
                                 precision_score as ps, recall_score as rs)
    ap = float(average_precision_score(y_bin, p_bin))
    pr, rc, _ = precision_recall_curve(y_bin, p_bin)
    p_r05 = float(pr[rc >= 0.5].max()) if (rc >= 0.5).any() else float("nan")
    best = None
    for thr in np.round(np.arange(0.05, 0.99, 0.01), 3):
        yp = (p_bin >= thr).astype(int)
        p_, r_ = ps(y_bin, yp, zero_division=0), rs(y_bin, yp)
        if p_ >= 0.7 and (best is None or r_ > best[2]):
            best = (float(thr), float(p_), float(r_))
    return {"pr_auc": ap, "prec@r>=.5": p_r05,
            "thr@P>=.7": None if best is None else best,
            "base": float(y_bin.mean())}


def calibration_oe(S, subjects, horizon_days, n_bins=10):
    """O/E-таблица калибровки: предсказанный риск события <= horizon vs наблюдённый.

    Только «полнонаблюдаемые» субъекты: событие в окне наблюдения ИЛИ
    дожитие до 30 дней без цензуры раньше срока.
    """
    step = int(round(horizon_days * tte.STEPS_PER_DAY)) - 1
    pred = 1.0 - S[:, step]
    obs = subjects["event_flag"].to_numpy(np.int8)
    days = subjects["obs_days"].to_numpy(float)
    full = (obs == 1) | (days >= min(horizon_days, tte.HORIZON_DAYS) - 0.05)
    y = ((obs == 1) & (days <= horizon_days + 1e-9)).astype(float)
    p = pred[full]
    q = pd.qcut(pd.Series(p), n_bins, duplicates="drop")
    tab = (pd.DataFrame({"q": q, "pred": p, "y": y[full]})
           .groupby("q", observed=True)
           .agg(n=("y", "size"), pred=("pred", "mean"), obs=("y", "mean"))
           .assign(oe=lambda d: d["obs"] / d["pred"].clip(lower=1e-6)))
    return tab


def baseline_survival_by_type(surv_train, types_train, types_test, eval_times):
    """Kaplan-Meier и Nelson-Aalen якоря по типам каналов (только train).

    Возвращает (S_km, S_na) — матрицы выживаемости (n_test, len(eval_times)).
    """
    from scipy.interpolate import interp1d
    from sksurv.nonparametric import kaplan_meier_estimator, nelson_aalen_estimator
    types = np.union1d(np.unique(types_train), np.unique(types_test))
    km_f, na_f = {}, {}
    for t_ in types:
        m = types_train == t_
        if m.sum() == 0:
            continue
        ev = surv_train["event"][m]
        tm = surv_train["time"][m]
        if not ev.any():          # в типе нет ни одного события в train
            continue
        kt, ks = kaplan_meier_estimator(ev, tm)
        km_f[t_] = interp1d(kt, ks, kind="previous", bounds_error=False,
                            fill_value=(ks[0], ks[-1])) if len(kt) else None
        nt, nh = nelson_aalen_estimator(ev, tm)
        na_f[t_] = interp1d(nt, np.exp(-nh), kind="previous", bounds_error=False,
                            fill_value=(np.exp(-nh[0]), np.exp(-nh[-1]))) if len(nt) else None
    n = len(types_test)
    S_km = np.ones((n, len(eval_times)))
    S_na = np.ones((n, len(eval_times)))
    for i, t_ in enumerate(types_test):
        f = km_f.get(t_)
        S_km[i] = f(eval_times) if f is not None else np.ones(len(eval_times))
        f = na_f.get(t_)
        S_na[i] = f(eval_times) if f is not None else np.ones(len(eval_times))
    return S_km, S_na
def fit_benchmarks(tr_sub, va_sub, ho_sub, X_cols, seed=42):
    """Бенчмарки на уровне субъекта (без person-time): CatBoost SurvivalAft, RSF.

    Возвращает dict безопасных для сравнения сущностей: риски и матрицы S.
    """
    from scipy.interpolate import interp1d

    X_tr = tr_sub[X_cols].fillna(tr_sub[X_cols].median(numeric_only=True))
    X_ho = ho_sub[X_cols].fillna(tr_sub[X_cols].median(numeric_only=True))
    surv_tr = tte.make_surv_struct(tr_sub["event_flag"], tr_sub["obs_days"])
    surv_ho = tte.make_surv_struct(ho_sub["event_flag"], ho_sub["obs_days"])
    times = tte.EVAL_TIMES
    out: dict = {}

    # ---- CatBoost SurvivalAft: интервальные метки [t0, t1]; right-censored = (t, -1) ----
    from catboost import CatBoostRegressor, Pool
    y_tr = np.stack([tr_sub["obs_days"].to_numpy(float),
                     np.where(tr_sub["event_flag"] == 1, tr_sub["obs_days"], -1.0).astype(float)],
                    axis=1)
    m = CatBoostRegressor(loss_function="SurvivalAft", iterations=300,
                          learning_rate=0.05, depth=6, random_seed=seed,
                          task_type="CPU", verbose=100)
    m.fit(Pool(X_tr, label=y_tr))
    a = m.predict(X_ho)  # location (log-шкала), sigma=1.0 (default scale)
    # S(t) = 1 - F_logistic((ln t - a) / 1.0)
    from scipy.stats import logistic
    Z = (np.log(times)[None, :] - a[:, None]) / 1.0
    S_aft = (1.0 - logistic.cdf(Z))
    out["survival_aft"] = {"S": S_aft, "risk": 1.0 - S_aft[:, -1]}

    # ---- Random Survival Forest (scikit-survival) ----
    from sksurv.ensemble import RandomSurvivalForest
    rsf = RandomSurvivalForest(n_estimators=150, max_depth=12, min_samples_leaf=10,
                               random_state=seed, n_jobs=-1)
    rsf.fit(X_tr, surv_tr)
    est = rsf.predict_survival_function(X_ho)
    S_rsf = np.zeros((len(est), len(times)))
    for i, fn in enumerate(est):
        S_rsf[i] = np.clip(fn.predict(times), 0, 1) if hasattr(fn, "predict") else 1.0
    out["rsf"] = {"S": S_rsf, "risk": 1.0 - S_rsf[:, -1]}
    return out
    n = len(types_test)
    S_km = np.ones((n, len(eval_times)))
    S_na = np.ones((n, len(eval_times)))
    for i, t_ in enumerate(types_test):
        f = km_f.get(t_)
        S_km[i] = f(eval_times) if f is not None else np.ones(len(eval_times))
        f = na_f.get(t_)
        S_na[i] = f(eval_times) if f is not None else np.ones(len(eval_times))
    return S_km, S_na
def main():
    ap = argparse.ArgumentParser(description="TTE survival experiment (layer 2)")
    ap.add_argument("--quick", action="store_true", help="малые выборки, быстрый прогон")
    ap.add_argument("--bench", action="store_true", help="бенчмарки SurvivalAft/RSF")
    ap.add_argument("--n-starts", type=int, default=25_000)
    ap.add_argument("--n-fault", type=int, default=18_000)
    ap.add_argument("--n-nonfault", type=int, default=18_000)
    ap.add_argument("--n-val", type=int, default=9_000)
    ap.add_argument("--n-hold", type=int, default=30_000)
    ap.add_argument("--iters", type=int, default=500)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--eval-only", action="store_true",
                    help="переиспользовать сохранённую модель (без обучения)")
    args = ap.parse_args()

    if args.quick:
        args.n_starts = 6_000
        args.n_fault = 4_000
        args.n_nonfault = 4_000
        args.n_val = 3_000
        args.n_hold = 5_000
        args.iters = 250
        args.depth = 5

    out_dir = pathlib.Path(__file__).resolve().parent / "models"
    out_dir.mkdir(exist_ok=True)
    report_path = pathlib.Path(__file__).resolve().parent / (
        f"tte_report_{pd.Timestamp.now():%Y%m%d_%H%M}.txt")
    log = []
    def say(msg=""):
        print(msg)
        log.append(str(msg))

    t0 = time.time()
    subjects = build_dataset()
    say(f"[main] таблица субъектов: {subjects.shape[0]:,} строк")
    train, val, holdout = tte.split_subjects(subjects)
    verify_no_lookup(train, val, holdout)

    X_cols = tte.subject_features(train)
    say(f"[main] фич: {len(X_cols)} | train={train.shape[0]:,} "
        f"val={val.shape[0]:,} holdout={holdout.shape[0]:,}")
    for name, s in (("train", train), ("val", val), ("holdout", holdout)):
        say(f"  {name}: событий {s['event_flag'].mean()*100:.1f}%, "
            f"медиана obs (дней) {s['obs_days'].median():.1f}, "
            f"цензур {100*(1-s['event_flag'].mean()):.1f}%")

    tr_sub = tte.sample_subjects(train, args.n_starts, args.n_fault,
                                 args.n_nonfault, seed=args.seed)
    va_sub = tte.sample_subjects(val, n_starts=args.n_val // 3,
                                 n_fault=args.n_val // 3, n_nonfault=args.n_val // 3,
                                 seed=args.seed + 1)
    ho_sub = tte.sample_holdout(holdout, args.n_hold, seed=777)

    say(f"[main] выборки: train={tr_sub.shape[0]:,} val={va_sub.shape[0]:,} "
        f"holdout={ho_sub.shape[0]:,}")

    if args.eval_only:
        X_tr = X_va = y_tr = y_va = None
        say("[main] eval-only: person-time не разворачиваем")
    else:
        X_tr, y_tr = tte.expand_person_time(tr_sub, X_cols, tte.HORIZON_BUCKETS)
        X_va, y_va = tte.expand_person_time(va_sub, X_cols, tte.HORIZON_BUCKETS)
        say(f"[main] person-time: train={X_tr.shape[0]:,} ({X_tr.shape[1]} колонок), "
            f"val={X_va.shape[0]:,}; событий в шаге: {y_tr.mean()*100:.3f}%")

    say("[train] CatBoost discrete hazard ...")
    model_fp = out_dir / "tte_discrete_hazard.cbm"
    if args.eval_only and model_fp.exists():
        from catboost import CatBoostClassifier
        m = CatBoostClassifier()
        m.load_model(model_fp)
        say(f"[train] модель загружена из {model_fp.name} (без обучения)")
    else:
        m = fit_discrete_hazard(X_tr, y_tr, X_va, y_va, iters=args.iters,
                                lr=args.lr, depth=args.depth, seed=args.seed)
        say(f"[train] готово за {time.time()-t0:.0f}s, итераций={m.get_best_iteration()}")
        m.save_model(model_fp)
        say(f"[save] model -> {model_fp}")
    imp = pd.Series(m.get_feature_importance(type="PredictionValuesChange"),
                    index=X_cols + ["шаг", "час_шага", "день_недели_шага", "месяц_шага", "доля_горизонта"])
    say("\nТоп-15 фич (hazard):\n" + imp.sort_values(ascending=False).head(15).round(3).to_string())

    surv_tr = tte.make_surv_struct(tr_sub["event_flag"], tr_sub["obs_days"])
    surv_ho = tte.make_surv_struct(ho_sub["event_flag"], ho_sub["obs_days"])

    S_ho = predict_survival_discrete(m, ho_sub, X_cols)
    risk_ho = 1.0 - S_ho[:, -1]
    m_metrics = survival_metrics(surv_tr, surv_ho, risk_ho, S_ho, tte.EVAL_TIMES)

    # Порог под Precision>=0.7 выбираем на ВНУТРЕННЕЙ валидации (<=2025-06-30),
    # держанный период (>=2025-07-01) используем только для финальной оценки.
    S_va = predict_survival_discrete(m, va_sub, X_cols)
    y_va24 = ((va_sub["event_flag"] == 1) & (va_sub["obs_days"] <= 1.01)).to_numpy(int)
    p_va24 = 1.0 - S_va[:, int(round(1.0 * tte.STEPS_PER_DAY)) - 1]
    thr_val = pick_threshold(y_va24, p_va24, min_precision=0.7)

    y_ho24 = ((ho_sub["event_flag"] == 1) & (ho_sub["obs_days"] <= 1.01)).to_numpy(int)
    p_ho24 = 1.0 - S_ho[:, int(round(1.0 * tte.STEPS_PER_DAY)) - 1]
    pr24_val = pr_at_horizon(y_va24, p_va24)
    pr24_ho = pr_at_horizon(y_ho24, p_ho24)
    if np.isfinite(thr_val[0]):
        from sklearn.metrics import precision_score as psx, recall_score as rsx
        yp = (p_ho24 >= thr_val[0]).astype(int)
        hold_p, hold_r = psx(y_ho24, yp, zero_division=0), rsx(y_ho24, yp)
    else:
        hold_p, hold_r = float("nan"), float("nan")
    oe30 = calibration_oe(S_ho, ho_sub, 30.0)

    say("\n=== DISCRETE HAZARD (CatBoost), holdout 2025H2+2026 ===")
    say(f"Uno-C={m_metrics['uno_c']:.4f} | meanAUC={m_metrics['mean_auc']:.4f} "
        f"| IBS={m_metrics['ibs']:.4f}")
    say("AUC по времени: " + str(m_metrics["auc_by_t"]))
    say("Brier: " + str(m_metrics["brier"]))
    say(f"P(24ч) на val (внутр. окно): PR-AUC={pr24_val['pr_auc']:.4f} "
        f"prec@r>=.5={pr24_val['prec@r>=.5']:.4f} база={pr24_val['base']*100:.1f}%")
    say(f"P(24ч) на holdout: PR-AUC={pr24_ho['pr_auc']:.4f} "
        f"prec@r>=.5={pr24_ho['prec@r>=.5']:.4f} база={pr24_ho['base']*100:.1f}% | "
        f"порог(val)={thr_val[0]:.2f} -> holdout precision={hold_p:.3f} recall={hold_r:.3f}")
    say("\nКалибровка 30д (O/E):\n" + oe30.round(3).to_string())

    # --- Якоря: KM / NA по типам каналов ---
    types_tr = tr_sub["тип_датчика"].to_numpy()
    types_ho = ho_sub["тип_датчика"].to_numpy()
    S_km, S_na = baseline_survival_by_type(surv_tr, types_tr, types_ho, tte.EVAL_TIMES)
    km_met = survival_metrics(surv_tr, surv_ho, 1.0 - S_km[:, -1], S_km, tte.EVAL_TIMES)
    na_met = survival_metrics(surv_tr, surv_ho, 1.0 - S_na[:, -1], S_na, tte.EVAL_TIMES)
    say("\n=== ЯКОРЯ (train-only, по типам) на holdout ===")
    say(f"KM:  Uno-C={km_met['uno_c']:.4f} IBS={km_met['ibs']:.4f}")
    say(f"NA:  Uno-C={na_met['uno_c']:.4f} IBS={na_met['ibs']:.4f}")

    # --- Бенчмарки ---
    if args.bench:
        say("\n=== БЕНЧМАРКИ (обучаются на train, оцениваются на holdout) ===")
        bm = fit_benchmarks(tr_sub, va_sub, ho_sub, X_cols, seed=args.seed)
        for name, d in bm.items():
            met = survival_metrics(surv_tr, surv_ho, d["risk"], d["S"], tte.EVAL_TIMES)
            say(f"{name}: Uno-C={met['uno_c']:.4f} meanAUC={met['mean_auc']:.4f} "
                f"IBS={met['ibs']:.4f}")

    # --- Аннотированные предсказания холдаута ---
    ho_out = ho_sub[["ид_канала_данных", "бакет", "дата", "тип_датчика",
                     "event_flag", "obs_days"]].copy()
    ho_out["p24"] = 1.0 - S_ho[:, int(round(1.0 * tte.STEPS_PER_DAY)) - 1]
    ho_out["risk30"] = risk_ho
    ho_out["exp_days"] = S_ho.sum(axis=1) / tte.STEPS_PER_DAY  # RMST, дни
    ho_out.to_parquet(out_dir / "tte_holdout_predictions.parquet", index=False)
    say(f"[save] предсказания holdout -> {out_dir / 'tte_holdout_predictions.parquet'}")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    say(f"[save] отчёт -> {report_path.name}")


if __name__ == "__main__":
    main()