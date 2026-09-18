# Бенчмарки на уровне субъекта: CatBoost SurvivalAft (интервальные метки) и RSF.
# Обучаются на train без person-time, оцениваются на том же холдауте.
if CFG["bench"]:
    bm = fit_benchmarks(tr_sub, va_sub, ho_sub, X_cols, seed=CFG["seed"])
    rows = []
    for name, d in bm.items():
        met = survival_metrics(surv_tr, surv_ho, d["risk"], d["S"], tte.EVAL_TIMES)
        rows.append({"модель": name, "Uno-C": round(met["uno_c"], 3),
                     "meanAUC": round(met["mean_auc"], 3), "IBS": round(met["ibs"], 3)})
    pd.DataFrame(rows)
else:
    print("бенчмарки отключены (CFG['bench'] = False)")