# Распределение показаний по типам датчиков (топ значений с долей от типа)
K = 12
tot_by_type = VAL_TYPE.groupby("тип_датчика")["n"].sum()
top_types = tot_by_type.sort_values(ascending=False).index[:10]

fig, axes = plt.subplots(2, 5, figsize=(19, 7))
for ax, tp in zip(axes.ravel(), top_types):
    tot = tot_by_type[tp]
    d = (VAL_TYPE[VAL_TYPE["тип_датчика"] == tp].head(K).copy())
    d["доля"] = d["n"] / tot
    d = d.iloc[::-1]
    ax.barh(d["значение"].str.slice(0, 34), d["доля"], color="steelblue")
    rest_share = 1 - d["доля"].sum()
    ax.set_title(f"{tp} · {tot:,.0f} (остальное {rest_share * 100:.1f}%)", fontsize=8)
    ax.set_xlabel("доля от типа", fontsize=7)
    ax.set_xlim(0, 1)
    ax.tick_params(axis="y", labelsize=6)
    ax.tick_params(axis="x", labelsize=6)
fig.suptitle("Топ-12 значений датчиков по типам (доля от записей типа)", fontsize=13)
fig.tight_layout(rect=[0, 0, 1, 0.97])
plt.show()