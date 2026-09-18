# Семантика показаний по объектам (тепловая карта долей)
sem_by_obj = (VAL_OBJ.groupby(["ид_объект", "семантика"])["n"].sum()
              .unstack(fill_value=0))
obj_order = sem_by_obj.sum(axis=1).sort_values(ascending=False).index[:15]
sbo = sem_by_obj.div(sem_by_obj.sum(axis=1), axis=0).loc[obj_order]

fig, ax = plt.subplots(figsize=(10, 7))
sns.heatmap(sbo, cmap="viridis", annot=True, fmt=".0%", annot_kws={"size": 7},
            cbar_kws={"label": "доля записей"}, ax=ax)
ax.set_title("Семантика показаний по объектам (топ-15)")
plt.tight_layout()
plt.show()