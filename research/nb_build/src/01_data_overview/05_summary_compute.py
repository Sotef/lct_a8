out_csv = du.find_dataset_dir() / "eda_summary.csv"
if RECOMPUTE or not out_csv.exists():
    summary_rows = []
    for fp in du.journal_files():
        year = fp.name.split("-")[2].split(".")[0]
        rows = alarms = 0
        ch_set = set()
        dates = []
        vals = set()
        for ch in du.read_chunks(fp, cols=["ид_канала_данных", "дата", "тревожное", "значение_датчика"]):
            rows += len(ch)
            ch_set.update(ch["ид_канала_данных"].unique().tolist())
            dates += [ch["дата"].min(), ch["дата"].max()]
            alarms += int((ch["тревожное"] == "t").sum())
            vals.update(ch["значение_датчика"].dropna().astype(str).unique().tolist())
        summary_rows.append({
            "год": year,
            "строк": rows,
            "уник_каналов": len(ch_set),
            "мин_дата": min(dates),
            "макс_дата": max(dates),
            "дней": (pd.to_datetime(max(dates)) - pd.to_datetime(min(dates))).days + 1,
            "тревожных": alarms,
            "доля_тревожных_%": round(100 * alarms / rows, 4),
            "уник_значений": len(vals),
        })
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(out_csv, index=False, encoding="utf-8-sig")
else:
    summary = pd.read_csv(out_csv, dtype={"год": str})
    print("Прочитано из готового артефакта:", out_csv)

summary