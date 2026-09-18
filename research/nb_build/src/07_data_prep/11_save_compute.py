out_panel = du.find_dataset_dir() / "train_panel_дым.csv"
daily_filled.to_csv(out_panel, index=False, encoding="utf-8-sig")
print("Сохранено:", out_panel.name, "| строк:", len(daily_filled))

# Итоговый состав
keep = ["ид_канала_данных", "дата", "год_неделя", "аномально", "цель_24ч"] + feat_cols + \
       [f"{c}_{w}д" for c in ("событий", "неисправностей", "тревог") for w in (3, 7, 14, 30)] + \
       ["z_событий"]
print("Колонки:", [c for c in keep if c in daily_filled.columns])