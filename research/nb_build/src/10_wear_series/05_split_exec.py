panel["ид_объект_code"] = panel["ид_объект"].astype("category").cat.codes
panel["тип_датчика_code"] = panel["тип_датчика"].astype("category").cat.codes

train, val, test = fe.split_by_time(panel)
drop_cols = (["ид_канала_данных", "бакет", "дата", "год_неделя", "аномально",
              "ид_объект", "тип_датчика", "серия_старт", "дни_до_серии", "дни_класс",
              "цель_6ч", "цель_12ч", "цель_24ч", "цель_48ч"]
             + [f"цель_серии_{n}" for n in fe.HORIZONS])
X_cols = [c for c in train.columns if c not in drop_cols]

print("Train:", train.shape, "| Val:", val.shape, "| Test:", test.shape)
print("Признаков:", len(X_cols))
for n in fe.HORIZONS:
    print(f"  цель_серии_{n}: base train={100 * train[f'цель_серии_{n}'].mean():.2f}% | "
          f"test={100 * test[f'цель_серии_{n}'].mean():.2f}%")