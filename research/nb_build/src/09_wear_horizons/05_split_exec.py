# Категориальные коды для бустинга
panel["ид_объект_code"] = panel["ид_объект"].astype("category").cat.codes
panel["тип_датчика_code"] = panel["тип_датчика"].astype("category").cat.codes

train, val, test = fe.split_by_time(panel)
drop_cols = ["ид_канала_данных", "бакет", "дата", "год_неделя", "аномально",
             "ид_объект", "тип_датчика"] + [f"цель_{n}" for n in fe.HORIZONS]
X_cols = [c for c in train.columns if c not in drop_cols]

print("Train:", train.shape, "| Val:", val.shape, "| Test:", test.shape)
print("Признаков:", len(X_cols))
print("\nДоля positive (train, вне кампаний):")
for n in fe.HORIZONS:
    print(f"  цель_{n}: {100 * train[f'цель_{n}'].mean():6.3f}%")