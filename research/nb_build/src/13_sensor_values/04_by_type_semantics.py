# Доля семантических групп по типам (стек)
sem_by_type = (VAL_TYPE.groupby(["тип_датчика", "семантика"])["n"].sum()
               .unstack(fill_value=0))
order = sem_by_type.sum(axis=1).sort_values(ascending=False).index
sbt = sem_by_type.div(sem_by_type.sum(axis=1), axis=0).loc[order]

ax = sbt.plot(kind="bar", stacked=True, figsize=(12, 5.5), colormap="tab10",
              width=0.85)
ax.legend(title="семантика", bbox_to_anchor=(1.01, 1), fontsize=8)
ax.set_ylabel("доля записей типа")
ax.set_title("Семантика показаний по типам датчиков")
plt.xticks(rotation=30, ha="right")
plt.tight_layout()
plt.show()