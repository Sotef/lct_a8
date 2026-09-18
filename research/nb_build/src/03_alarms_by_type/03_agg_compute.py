out_csv = du.find_dataset_dir() / "alarms_by_type_year.csv"
if RECOMPUTE or not out_csv.exists():
    ref_ch = du.load_ref_channels()[["ид_канала_данных", "тип_датчика", "тип_инж_системы"]]
    rows_all = []
    for fp in du.journal_files():
        year = fp.name.split("-")[2].split(".")[0]
        alarm_by_ch = {}
        for ch in du.read_chunks(fp, cols=["ид_канала_данных", "тревожное"]):
            al = ch.loc[ch["тревожное"] == "t", "ид_канала_данных"].value_counts()
            alarm_by_ch = pd.Series(alarm_by_ch).add(al, fill_value=0).astype("int64").to_dict()
        s = pd.Series(alarm_by_ch, dtype="int64").rename("alarms").to_frame() \
              .reset_index().rename(columns={"index": "ид_канала_данных"})
        s = s.merge(ref_ch, on="ид_канала_данных", how="left")
        s["тип_датчика"] = s["тип_датчика"].fillna("(нет в справочнике)")
        g = s.groupby(["тип_инж_системы", "тип_датчика"])["alarms"].sum()
        rows_all.append(pd.DataFrame({
            "год": year,
            "подсистема": g.index.get_level_values(0),
            "тип_датчика": g.index.get_level_values(1),
            "тревог": g.values,
        }))
        print(f"[{year}] ok", flush=True)
    at = pd.concat(rows_all)
    at.to_csv(out_csv, index=False, encoding="utf-8-sig")
else:
    at = pd.read_csv(out_csv, dtype={"год": str})
    print("Прочитано из готового артефакта:", out_csv)

print("\nТоп-20 (подсистема, тип) за все годы:")
print(at.groupby(["подсистема", "тип_датчика"])["тревог"].sum()
        .sort_values(ascending=False).head(20).to_string())