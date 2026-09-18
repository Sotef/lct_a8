# Помечаем кампании
w2 = du.add_campaign_flags(weekly)
print("Недель кампаний:", int(w2["is_campaign"].sum()))
print(w2[w2["is_campaign"]].to_string(index=False))

# Сравнение
print("\n=== Средняя неделя: кампании vs чистые ===")
comp = w2.groupby("is_campaign")[["событий", "тревог", "доля_тревог_%"]].mean()
comp.index = ["чистые" if not i else "кампании" for i in comp.index]
print(comp.to_string())

# Чистые недели (для будущих сплитов)
clean = du.filter_clean_weeks(weekly)
print("\nЧистых недель остаётся:", len(clean), "из", len(weekly))