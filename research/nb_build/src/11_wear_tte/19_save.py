# Сохранение аннотированных предсказаний холдаута (для сервиса / будущей разметки).
out = ho_sub[["ид_канала_данных", "бакет", "дата", "тип_датчика",
              "event_flag", "obs_days"]].copy()
out["p24"] = p_ho24
out["risk30"] = risk_ho
out["exp_days"] = S_ho.sum(axis=1) / tte.STEPS_PER_DAY   # RMST: ожидаемые дни в горизонте
out.to_parquet(RESEARCH / "models" / "tte_holdout_predictions.parquet", index=False)
print("сохранено:", out.shape)
out.head()