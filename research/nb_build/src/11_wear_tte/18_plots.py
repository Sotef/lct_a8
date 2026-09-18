# Примеры кривых S(t) и средняя кривая по квинтилям риска.
grid_d = np.arange(1, tte.HORIZON_BUCKETS + 1) / tte.STEPS_PER_DAY
i_hi = int(np.argmax(p_ho24)); i_lo = int(np.argmin(p_ho24))

fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
axes[0].step(grid_d, S_ho[i_hi], where="post",
             label=f"max P24 (канал {ho_sub['ид_канала_данных'].iloc[i_hi]})")
axes[0].step(grid_d, S_ho[i_lo], where="post",
             label=f"min P24 (канал {ho_sub['ид_канала_данных'].iloc[i_lo]})")
axes[0].set_title("S(t): каналы с высоким/низким риском")
axes[0].set_xlabel("дни"); axes[0].set_ylabel("S(t)")

q = pd.qcut(p_ho24, 5, duplicates="drop").codes
for qi in range(5):
    axes[1].step(grid_d, S_ho[q == qi].mean(axis=0), where="post",
                 label=f"квинтиль {qi + 1} по P24")
axes[1].set_title("Средняя S(t) по квинтилям P(24ч)")
axes[1].set_xlabel("дни")
for ax in axes:
    ax.grid(alpha=0.3); ax.legend(fontsize=8)
plt.tight_layout(); plt.show()

# IPCW Brier по времени (holdout)
bd = (pd.Series(met_ho["brier"]).astype(float).sort_index())
fig, ax = plt.subplots(figsize=(6, 4))
ax.plot(bd.index.astype(float), bd.values, marker="o")
ax.set_xlabel("t, дни"); ax.set_ylabel("IPCW Brier")
ax.set_title("IPCW Brier по времени (holdout)")
ax.grid(alpha=0.3)
plt.tight_layout(); plt.show()