# Распределение показаний по объектам (топ-10 объектов, топ-6 значений со стеком)
K_OBJ = 6
tot_by_obj = VAL_OBJ.groupby("ид_объект")["n"].sum()
top_objs = tot_by_obj.sort_values(ascending=False).index[:10]

d = VAL_OBJ[VAL_OBJ["ид_объект"].isin(top_objs)].copy()
d["доля"] = d["n"] / d["ид_объект"].map(tot_by_obj)
melt = []
for o in top_objs:
    top6 = d[d["ид_объект"] == o].head(K_OBJ)
    melt.append(top6.assign(значение=top6["значение"].str.slice(0, 22)))
rest = d[~d["значение"].isin(melt[0]["значение"].values)] if melt else d.iloc[0:0]

fig, ax = plt.subplots(figsize=(13, 6))
bottom = np.zeros(len(top_objs))
cmap = plt.cm.Set2
for j, o in enumerate(top_objs):
    sub = d[d["ид_объект"] == o].head(K_OBJ)
    sub_lab = sub["значение"].str.slice(0, 20).tolist()
    cum = 0.0
    for i, (lab, sh) in enumerate(zip(sub_lab, sub["доля"])):
        ax.barh(o, sh, left=cum, color=cmap(i % 8), label=lab if j == 0 else None)
        cum += sh
    ax.text(cum + 0.01, j, f"{tot_by_obj[o]:,}", va="center", fontsize=7)
ax.set_xlabel("доля от записей объекта")
ax.set_title("Топ-10 объектов по числу записей: доля топ-6 значений")
ax.legend(bbox_to_anchor=(1.01, 1), fontsize=8, loc="upper left")
plt.tight_layout()
plt.show()

tot_by_obj.head(10)