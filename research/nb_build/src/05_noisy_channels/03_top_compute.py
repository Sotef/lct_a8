out_csv = du.find_dataset_dir() / "top_channels_2025.csv"
year = "2025"
fp = next(f for f in du.journal_files() if year in f.name)
counts = {}
for ch in du.read_chunks(fp, cols=["ид_канала_данных", "тревожное"]):
    counts.update(ch["ид_канала_данных"].value_counts().to_dict())
top = pd.Series(counts).sort_values(ascending=False)
top.rename("событий").to_csv(out_csv, encoding="utf-8-sig")

ref_ch = du.load_ref_channels()[["ид_канала_данных", "тип_датчика", "название_датчика"]]
top_df = (top.head(20).rename("событий").to_frame()
          .reset_index().rename(columns={"index": "ид_канала_данных"}))
top_df = top_df.merge(ref_ch, on="ид_канала_данных", how="left")
print(f"Топ-20 шумных каналов ({year}):")
print(top_df.to_string(index=False))