# Распределение данных по объектам
obj_stats = (panel.groupby("ид_объект")
                  .agg(строк=("дата", "size"),
                       каналов=("ид_канала_данных", "nunique"),
                       pos=("цель_24ч", "mean"))
                  .sort_values("строк", ascending=False))
print("Объектов с WEAR-каналами:", len(obj_stats))
print(obj_stats.head(12).round(3).to_string())

N_LOCAL = 30000  # мин. строк для локальной модели
big_objs = obj_stats[obj_stats["строк"] >= N_LOCAL].index.tolist()
print(f"\nОбъектов, пригодных для локальной модели (>= {N_LOCAL} строк): {len(big_objs)}")