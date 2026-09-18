# Слой «вероятность события в 24ч» выводится из S(t): P = 1 - S(24ч).
from sklearn.metrics import precision_recall_curve

y_va24 = ((va_sub["event_flag"] == 1) & (va_sub["obs_days"] <= 1.01)).to_numpy(int)
p_va24 = 1 - S_va[:, int(round(1.0 * tte.STEPS_PER_DAY)) - 1]
y_ho24 = ((ho_sub["event_flag"] == 1) & (ho_sub["obs_days"] <= 1.01)).to_numpy(int)
p_ho24 = 1 - S_ho[:, int(round(1.0 * tte.STEPS_PER_DAY)) - 1]

thr = pick_threshold(y_va24, p_va24, min_precision=0.7)
prv, prh = pr_at_horizon(y_va24, p_va24), pr_at_horizon(y_ho24, p_ho24)
print("P(24ч) val:     PR-AUC=%.4f prec@r>=.5=%.4f база=%.1f%%" % (
    prv["pr_auc"], prv["prec@r>=.5"], 100 * prv["base"]))
print("P(24ч) holdout: PR-AUC=%.4f prec@r>=.5=%.4f база=%.1f%%" % (
    prh["pr_auc"], prh["prec@r>=.5"], 100 * prh["base"]))
print("порог(val) под Precision>=0.7:", np.round(thr, 3) if np.isfinite(thr[0]) else "недостижим")
if np.isfinite(thr[0]):
    from sklearn.metrics import precision_score as ps, recall_score as rs
    yp = (p_ho24 >= thr[0]).astype(int)
    print("holdout при пороге(val): precision=%.3f recall=%.3f" % (
        ps(y_ho24, yp, zero_division=0), rs(y_ho24, yp)))

pr_, rc_, _ = precision_recall_curve(y_ho24, p_ho24)
fig, ax = plt.subplots(figsize=(6, 4.5))
ax.plot(rc_, pr_, lw=2, color="C0")
ax.set_xlabel("Recall"); ax.set_ylabel("Precision")
ax.set_title("PR-кривая P(24ч), holdout 2025H2+2026")
ax.grid(alpha=0.3)
plt.tight_layout(); plt.show()