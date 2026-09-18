text = vc[~vc.index.map(du.is_numeric_value)]
text.rename("счет").to_csv(du.find_dataset_dir() / "text_status_counts_all_years.csv",
                           encoding="utf-8-sig")
print("Текстовых статусов:", len(text))
print(text.head(30).to_string())