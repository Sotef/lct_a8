out_csv = du.find_dataset_dir() / "value_counts_all_years.csv"
if RECOMPUTE or not out_csv.exists():
    all_vals = {}
    for fp in du.journal_files():
        for ch in du.read_chunks(fp, cols=["значение_датчика", "ид_канала_данных"]):
            for v, c in ch["значение_датчика"].fillna("(пусто)").value_counts().items():
                all_vals[v] = all_vals.get(v, 0) + int(c)
    vc = pd.Series(all_vals).sort_values(ascending=False)
    vc.rename("счет").to_csv(out_csv, encoding="utf-8-sig")
else:
    vc = pd.read_csv(out_csv, index_col=0).iloc[:, 0]
    print("Прочитано из готового артефакта:", out_csv)

print("Уникальных значений:", len(vc))
print(vc.head(25).to_string())