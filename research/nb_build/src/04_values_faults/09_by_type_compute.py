ref_ch = du.load_ref_channels()[["ид_канала_данных", "тип_датчика"]]
targets = ["Датчик дыма", "Датчик температуры", "Газовый датчик",
           "Состояние насоса", "КД Дверь", "Датчик движения"]
files = du.journal_files()
for t in targets:
    stats = {}
    for fp in files:
        for ch in du.read_chunks(fp, cols=["ид_канала_данных", "значение_датчика"]):
            m = ch.merge(ref_ch, on="ид_канала_данных", how="left")
            m = m[m["тип_датчика"] == t]
            for v, c in m["значение_датчика"].fillna("(пусто)").value_counts().items():
                if du.is_numeric_value(v):
                    continue
                stats[v] = stats.get(v, 0) + int(c)
    top = pd.Series(stats).sort_values(ascending=False)
    print(f"\n-- {t} (топ-8 текстовых статусов) --")
    print(top.head(8).to_string())