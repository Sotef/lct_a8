import warnings
warnings.filterwarnings("ignore")
from catboost import CatBoostClassifier, Pool
from sklearn.metrics import (average_precision_score, precision_recall_curve,
                             f1_score, precision_score as ps, recall_score as rs)

ITERS, LR, DEPTH, ES = 500, 0.05, 6, 200
rows = []
preds_series = {}
for name in fe.HORIZONS:
    y_col = f"цель_серии_{name}"
    tr = train.dropna(subset=[y_col])
    va = val.dropna(subset=[y_col])
    te = test.dropna(subset=[y_col])
    m = CatBoostClassifier(iterations=ITERS, learning_rate=LR, depth=DEPTH, random_seed=42,
                           task_type="CPU", eval_metric="F1", early_stopping_rounds=ES, verbose=0)
    m.fit(Pool(tr[X_cols], tr[y_col]), eval_set=Pool(va[X_cols], va[y_col]))
    yp = m.predict_proba(te[X_cols])[:, 1]
    yt = te[y_col].astype(int).values
    preds_series[name] = yp
    base = yt.mean()
    ap = average_precision_score(yt, yp)
    pr, rc, _ = precision_recall_curve(yt, yp)
    p_r05 = float(pr[rc >= 0.5].max()) if (rc >= 0.5).any() else float("nan")
    f1 = float(f1_score(yt, (yp >= 0.5).astype(int)))
    best = None
    for thr in np.round(np.arange(0.10, 0.99, 0.01), 3):
        ypr = (yp >= thr).astype(int)
        p_, r_ = ps(yt, ypr, zero_division=0), rs(yt, ypr)
        if p_ >= 0.7 and (best is None or r_ > best[2]):
            best = (thr, p_, r_)
    rows.append({"горизонт": name, "база,%": round(100 * base, 2),
                 "PR-AUC": round(ap, 4), "lift": round(ap / base, 2),
                 "Prec@R>=.5": round(p_r05, 4), "F1@.5": round(f1, 4),
                 "thr@P>=.7": (None if best is None else best[0]),
                 "Rec@thr": (None if best is None else round(best[2], 3))})
    print(f"  {name}: PR-AUC={ap:.4f} lift={ap / base:.1f}x")
res = pd.DataFrame(rows)
print("\nСлой 1 (старты серий) — тест 2026:")
print(res.to_string(index=False))