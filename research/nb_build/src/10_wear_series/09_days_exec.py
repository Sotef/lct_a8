from catboost import CatBoostClassifier as CatBoostMC
from scipy.stats import spearmanr

X_tr = train[X_cols]
m_days = CatBoostMC(iterations=700, learning_rate=0.05, depth=6, random_seed=42,
                    loss_function="MultiClass", eval_metric="Accuracy",
                    early_stopping_rounds=200, verbose=0)
m_days.fit(Pool(X_tr, train["дни_класс"]),
           eval_set=Pool(val[X_cols], val["дни_класс"]))
proba = m_days.predict_proba(test[X_cols])
pred_cls = proba.argmax(axis=1)
exp_days = proba @ MID

y_true_cls = test["дни_класс"].values
obs = test["дни_до_серии"].notna().values  # нецензурные строки: есть реальное событие
true_d = test["дни_до_серии"].values[obs]
exp_o = exp_days[obs]
err = np.abs(exp_o - true_d)
mae = err.mean()
med = np.median(err)
corr = spearmanr(exp_o, true_d).statistic
acc1 = np.mean(np.abs(pred_cls[obs] - y_true_cls[obs]) <= 1)

print("Слой 2 (дни до события), тест 2026, нецензурные строки (n=%d):" % obs.sum())
print(f"  MAE (дней):            {mae:.2f}")
print(f"  медиана |ошибки|:      {med:.2f}")
print(f"  Спирмен(ожид., факт.): {corr:.4f}")
print(f"  доля класса +-1 бин:   {100 * acc1:.2f}%")
print(f"  цензурировано на тесте: {100 * (1 - obs.mean()):.2f}%")
print("\nСвязь слоёв: корреляция P(событие в 24ч) vs ожидаемые дни = %.3f"
      % np.corrcoef(preds_series["24ч"], exp_days)[0, 1])
print("\nОжидаемые дни по группам P(24ч):")
qm = pd.qcut(pd.Series(preds_series["24ч"]), 4, duplicates="drop")
print(pd.Series(exp_days).groupby(qm).mean().round(1).to_string())