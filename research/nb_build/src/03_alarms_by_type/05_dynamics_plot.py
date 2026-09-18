import matplotlib.pyplot as plt

key = ["Датчик дыма", "Газовый датчик", "Тепловой датчик", "Датчик температуры",
       "Датчик движения", "КД Дверь", "Состояние насоса", "Датчик затопления"]
wide = (at[at["тип_датчика"].isin(key)]
        .pivot_table(index="тип_датчика", columns="год",
                     values="тревог", aggfunc="sum", fill_value=0))
print(wide.to_string())

wide.T.plot(figsize=(12, 5), marker="o", title="Тревоги по типам датчиков по годам")
plt.xticks(rotation=0)
plt.legend(bbox_to_anchor=(1.0, 1.0))
plt.show()