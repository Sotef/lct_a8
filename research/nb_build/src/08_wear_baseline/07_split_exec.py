# Добавляем тип датчика из справочника и категориальные коды
ref_ch = du.load_ref_channels()[["ид_канала_данных", "тип_датчика"]]
panel = panel.merge(ref_ch, on="ид_канала_данных", how="left")

# label-кодировка категорий для бустинга (sklearn LabelEncoder не обязателен)
panel["ид_объект_code"] = panel["ид_объект"].astype("category").cat.codes
panel["тип_датчика_code"] = panel["тип_датчика"].astype("category").cat.codes

train, val, test = fe.split_by_time(panel)

drop_cols = ["ид_канала_данных", "дата", "год_неделя", "аномально",
             "цель_24ч", "дата_dt", "ид_объект", "тип_датчика"]
y_col = "цель_24ч"
X_cols = [c for c in train.columns
          if c not in drop_cols and c != y_col]

print("Train:", train.shape, "| Val:", val.shape, "| Test:", test.shape)
print("\nХ признаков:", len(X_cols))
print("Доля positive: train=%.3f%% val=%.3f%% test=%.3f%%" % (
    train[y_col].mean() * 100, val[y_col].mean() * 100, test[y_col].mean() * 100))