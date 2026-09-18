out_csv = du.find_dataset_dir() / "channel_tag_parsed.csv"
parsed = ref_ch["тег_инженерной_системы"].apply(du.parse_tag).apply(pd.Series)
parsed.insert(0, "ид_канала_данных", ref_ch["ид_канала_данных"].values)
parsed["название_датчика"] = ref_ch["название_датчика"].values
parsed.to_csv(out_csv, index=False, encoding="utf-8-sig")

print("Топ значений p1 (коллекторы):")
print(parsed["p1"].value_counts().head(15).to_string())
print("\nРаспределение p5 (номер канала в точке):")
print(parsed["p5"].value_counts().head(10).to_string())
parsed.head(8)