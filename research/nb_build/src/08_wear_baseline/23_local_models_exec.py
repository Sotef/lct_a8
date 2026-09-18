# Локальные модели по объектам (CatBoost CPU): 1000 итераций, depth 5, lr 0.03
from catboost import CatBoostClassifier, Pool
from sklearn.metrics import average_precision_score

LOCAL_ITERS = 1000
LOCAL_DEPTH = 5
LOCAL_ES = 400

res_local = []
y_test_all = test[y_col].astype(int).values
for obj in big_objs:
    train_o = train[train["ид_объект"] == obj]
    val_o = val[val["ид_объект"] == obj]
    test_o = test[test["ид_объект"] == obj]
    if len(train_o) < 2000 or len(test_o) < 50 or len(val_o) == 0:
        continue
    m = CatBoostClassifier(iterations=LOCAL_ITERS, learning_rate=0.03, depth=LOCAL_DEPTH,
                           random_seed=42, task_type="CPU", verbose=False,
                           eval_metric="F1", early_stopping_rounds=LOCAL_ES)
    m.fit(train_o[X_cols], train_o[y_col],
          eval_set=Pool(val_o[X_cols], val_o[y_col]))
    yp = m.predict_proba(test_o[X_cols])[:, 1]
    ap = average_precision_score(test_o[y_col].astype(int), yp)
    idx_global = test["ид_объект"] == obj
    ap_global = average_precision_score(y_test_all[idx_global],
                                        preds["CatBoost"][idx_global])
    res_local.append((obj, len(train_o), round(ap_global, 4), round(ap, 4)))

res_df = pd.DataFrame(res_local, columns=["объект", "train_строк", "АП_общая", "АП_локальная"])
print("Сравнение: общая модель vs локальная по объекту (тест 2026)")
print(res_df.to_string(index=False))
print("\nСредняя АП: общая=%.4f локальная=%.4f" % (
    res_df["АП_общая"].mean(), res_df["АП_локальная"].mean()))