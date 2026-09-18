# Сортировка по каналу и дате
daily_filled = daily_filled.sort_values(["ид_канала_данных", "дата"]).reset_index(drop=True)
daily_filled["дата_dt"] = pd.to_datetime(daily_filled["дата"])

f = daily_filled.groupby("ид_канала_данных", sort=False)
for w in (3, 7, 14, 30):
    daily_filled[f"событий_{w}д"] = f["событий"].transform(
        lambda s: s.rolling(w, min_periods=1).sum())
    daily_filled[f"неисправностей_{w}д"] = f["неисправностей"].transform(
        lambda s: s.rolling(w, min_periods=1).sum())
    daily_filled[f"тревог_{w}д"] = f["тревог"].transform(
        lambda s: s.rolling(w, min_periods=1).sum())

# z-скор частоты относительно медианы канала (по чистым дням)
ch_med_events = clean.groupby("ид_канала_данных")["событий"].median()
ch_iqr = clean.groupby("ид_канала_данных")["событий"].quantile(0.75) - \
         clean.groupby("ид_канала_данных")["событий"].quantile(0.25)
daily_filled["z_событий"] = (daily_filled["событий"] - daily_filled["ид_канала_данных"].map(ch_med_events)) / \
                            (daily_filled["ид_канала_данных"].map(ch_iqr) + 1e-6)

# Целевая переменная: неисправность в следующие 24 часа (по исходным, НЕ замененным данным)
target = daily.sort_values(["ид_канала_данных", "дата"]).reset_index(drop=True)
t = target.groupby("ид_канала_данных", sort=False)
# сдвигаем флаг неисправности вверх на 1 день → «была неисправность в следующие 24ч»
daily_filled["цель_24ч"] = t["неисправностей"].transform(
    lambda s: s.shift(-1).fillna(0).gt(0).astype(int))
# аномальные дни исключаем из обучения (цель обесцениваем)
daily_filled.loc[daily_filled["аномально"], "цель_24ч"] = np.nan

print("Доля положительных (по чистым дням):",
      round(daily_filled["цель_24ч"].mean() * 100, 3), "%")
print(daily_filled["цель_24ч"].value_counts(dropna=False).to_dict())