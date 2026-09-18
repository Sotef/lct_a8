import matplotlib.pyplot as plt

w = weekly.copy()
w["x"] = w["год_неделя"].astype(int)

fig, axes = plt.subplots(3, 1, figsize=(15, 11), sharex=True)
w.plot(x="x", y="событий", ax=axes[0], legend=False, title="Событий по неделям")
axes[0].set_xlabel("")
w.plot(x="x", y="тревог", ax=axes[1], color="C3", legend=False, title="Тревог по неделям")
axes[1].set_xlabel("")
w.plot(x="x", y="доля_тревог_%", ax=axes[2], color="C2", legend=False, title="Доля тревог %")
axes[2].tick_params(axis="x", rotation=45)
plt.tight_layout()
plt.show()

# Тревоги ключевых типов по неделям
key = ["Датчик дыма", "Датчик движения", "Состояние насоса", "Газовый датчик"]
atk = at[at["тип_датчика"].isin(key)].copy()
atk["x"] = atk["год_неделя"].astype(int)
piv = atk.pivot_table(index="x", columns="тип_датчика", values="тревог", aggfunc="sum", fill_value=0)
piv.plot(figsize=(15, 5), title="Тревоги ключевых типов по неделям")
plt.tight_layout()
plt.show()