# Топ-20 значений по всему парку и по типам
overall = VAL_TYPE.groupby("значение", as_index=False)["n"].sum().sort_values("n", ascending=False)
overall.insert(1, "доля, %", (100 * overall["n"] / overall["n"].sum()).round(2))
overall.head(20)

print("по типам (суммарно записей):")
g = VAL_TYPE.groupby("тип_датчика")["n"].sum().sort_values(ascending=False)
pd.DataFrame({"записей": g, "доля, %": (100 * g / g.sum()).round(2)}).round(0)