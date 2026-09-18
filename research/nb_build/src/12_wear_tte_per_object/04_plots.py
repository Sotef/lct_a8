# Графики сравнения: scatter лок vs глоб (Uno-C), дельты, IBS
fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))

ax = axes[0]
ax.plot([0, 1], [0, 1], "--", color="gray")
ax.scatter(df["uno_c_глоб"], df["uno_c_лок"], s=50, color="C0")
for _, r in df.iterrows():
    ax.annotate(int(r["объект"]), (r["uno_c_глоб"], r["uno_c_лок"]), fontsize=7)
ax.set_xlabel("глобальная (Uno-C)"); ax.set_ylabel("локальная (Uno-C)")
ax.set_title("Uno-C по объектам: локальная vs глобальная")
ax.grid(alpha=0.3)

ax = axes[1]
delta = (df["uno_c_лок"] - df["uno_c_глоб"]).sort_values()
ax.barh([str(o) for o in df.loc[delta.index, "объект"]], delta.values, color=[
    "C2" if v > 0 else "C3" for v in delta])
ax.axvline(0, color="gray", lw=0.8)
ax.set_xlabel("delta Uno-C (лок - глоб)")
ax.set_title("Дельта по объектам")

ax = axes[2]
ax.scatter(df["ibs_глоб"], df["ibs_лок"], s=50, color="C1")
ax.plot([0, 0.2], [0, 0.2], "--", color="gray")
ax.set_xlabel("глобальная (IBS)"); ax.set_ylabel("локальная (IBS)")
ax.set_title("IBS: локальная vs глобальная (ниже = лучше)")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.show()