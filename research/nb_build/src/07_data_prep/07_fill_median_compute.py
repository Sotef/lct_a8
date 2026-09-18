daily = pd.read_csv(du.find_dataset_dir() / "daily_agg_2019_2026_дым.csv",
                    dtype={"ид_канала_данных": str, "дата": str})

# ISO-неделя из даты
iso = pd.to_datetime(daily["дата"]).dt.isocalendar()
daily["год_неделя"] = iso["year"].astype(int) * 100 + iso["week"].astype(int)
daily["аномально"] = daily["год_неделя"].map(du.week_is_campaign)

print("Строк панели:", len(daily), "| аномальных дней:", int(daily["аномально"].sum()))

# Медиана по чистым дням канала (для замены)
FEAT_BASE = ["событий", "тревог", "неисправностей", "шума"]
feat_cols = [c for c in FEAT_BASE + ["медиана_знач"] if c in daily.columns]
clean = daily[~daily["аномально"]]
ch_med = clean.groupby("ид_канала_данных")[feat_cols].median()

# Замена аномальных дней на медиану канала (векторно через map)
daily_filled = daily.copy()
# pandas 3.0 строг к типам: заранее приводим признаки к float, чтобы вписать медианы
daily_filled[feat_cols] = daily_filled[feat_cols].astype(float)
anom_mask = daily_filled["аномально"].values
ch_med_map = ch_med.reindex(daily_filled["ид_канала_данных"].unique()).fillna(
    clean[feat_cols].median())  # fallback для каналов без чистых дней
vals = ch_med_map.loc[daily_filled["ид_канала_данных"].values].values
daily_filled.loc[anom_mask, feat_cols] = vals[anom_mask]

print("\nДо/после (пример аномального дня, канал с большим всплеском):")
big = daily.loc[daily["аномально"], "событий"].idxmax()
print("аномальный день, канал:", daily.loc[big, "ид_канала_данных"],
      daily.loc[big, "дата"], "было:", daily.loc[big, feat_cols].round(2).tolist())
print("стало:", daily_filled.loc[big, feat_cols].round(2).tolist())
print("медиана канала:", ch_med.loc[daily.loc[big, "ид_канала_данных"], feat_cols].round(2).tolist())