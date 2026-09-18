from sklearn.metrics import average_precision_score, precision_recall_curve, f1_score as f1s

results = []
preds = {}
for name, m in [("LGBM(CPU)", lgbm), ("XGB(GPU)", xgbm), ("CatBoost", catb)]:
    yt = test[y_col].astype(int).values
    if name == "CatBoost":
        yp = m.predict_proba(test[X_cols])[:, 1]
    elif name == "XGB(GPU)":
        yp = m.predict(_dm_test)
    else:  # LGBM (Booster)
        yp = m.predict(test[X_cols])
    preds[name] = yp
    ap = average_precision_score(yt, yp)
    pr, rc, _ = precision_recall_curve(yt, yp)
    p_at_r = float(pr[rc >= 0.5].max()) if (rc >= 0.5).any() else float("nan")
    f1_05 = float(f1s(yt, (yp >= 0.5).astype(int)))
    results.append((name, round(ap, 4), round(p_at_r, 4), round(f1_05, 4)))

res = pd.DataFrame(results, columns=["модель", "PR-AUC", "Precision@R>=0.5", "F1@0.5"])
print("Результаты на тесте 2026 (без кампаний):")
print(res.to_string(index=False))

# Явный подбор порога: перебор, прямое вычисление precision/recall
from sklearn.metrics import precision_score as ps, recall_score as rs

print("\nПороги для recall при precision>=0.7 (явный перебор):")
for name, yp in preds.items():
    yt = test[y_col].astype(int).values
    best = None
    for thr in np.round(np.arange(0.30, 0.99, 0.01), 3):
        ypred = (yp >= thr).astype(int)
        p, r = ps(yt, ypred, zero_division=0), rs(yt, ypred)
        if p >= 0.7 and (best is None or r > best[1]):
            best = (thr, p, r)
    if best:
        print(f"  {name}: thr={best[0]:.2f} precision={best[1]:.3f} recall={best[2]:.3f}")
    else:
        print(f"  {name}: Precision>=0.7 не достигнута ни на одном пороге")