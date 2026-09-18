import warnings
warnings.filterwarnings("ignore")
from catboost import CatBoostClassifier, Pool
from sklearn.metrics import (average_precision_score, precision_recall_curve,
                             f1_score, precision_score as ps, recall_score as rs)

ITERS, LR, DEPTH, ES = 700, 0.05, 6, 300
rows = []
for name in fe.HORIZONS:
    y_col = f"цель_{name}"
    tr = train.dropna(subset=[y_col])
    va = val.dropna(subset=[y_col])
    te = test.dropna(subset=[y_col])
    m = CatBoostClassifier(iterations=ITERS, learning_rate=LR, depth=DEPTH,
                           random_seed=42, task_type="CPU", eval_metric="F1",
                           early_stopping_rounds=ES, verbose=100)
    m.fit(Pool(tr[X_cols], tr[y_col]), eval_set=Pool(va[X_cols], va[y_col]))
    yp = m.predict_proba(te[X_cols])[:, 1]
    yt = te[y_col].astype(int).values
    ap = average_precision_score(yt, yp)
    pr, rc, _ = precision_recall_curve(yt, yp)
    p_r05 = float(pr[rc >= 0.5].max()) if (rc >= 0.5).any() else float("nan")
    f1 = float(f1_score(yt, (yp >= 0.5).astype(int)))
    best = None
    for thr in np.round(np.arange(0.20, 0.99, 0.01), 3):
        ypr = (yp >= thr).astype(int)
        p_, r_ = ps(yt, ypr, zero_division=0), rs(yt, ypr)
        if p_ >= 0.7 and (best is None or r_ > best[2]):
            best = (thr, p_, r_)
    rows.append({
        "горизонт": name, "база,%": round(100 * yt.mean(), 2),
        "PR-AUC": round(ap, 4), "Prec@R>=.5": round(p_r05, 4), "F1@.5": round(f1, 4),
        "thr@P>=.7": (None if best is None else best[0]),
        "Prec@thr": (None if best is None else round(best[1], 3)),
        "Rec@thr": (None if best is None else round(best[2], 3)),
    })
    print(f"Горизонт {name}: PR-AUC={ap:.4f}, iters={m.get_best_iteration()}")

res = pd.DataFrame(rows)
print("\nРезультаты на тесте 2026 (без кампаний):")
print(res.to_string(index=False))

# Как падает PR-AUC с горизонтом
plt.figure(figsize=(8, 4.2))
plt.plot(res["горизонт"], res["PR-AUC"], marker="o", linewidth=2, color="C0")
plt.title("PR-AUC по горизонту прогноза (тест 2026)")
plt.ylabel("PR-AUC")
plt.grid(alpha=0.3)
plt.ylim(0, 1)
plt.show()