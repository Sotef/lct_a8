# Якоря: Kaplan-Meier и Nelson-Aalen по типам каналов (оценены ТОЛЬКО по train)
S_km, S_na = baseline_survival_by_type(
    surv_tr, tr_sub["тип_датчика"].to_numpy(),
    ho_sub["тип_датчика"].to_numpy(), tte.EVAL_TIMES)
km_met = survival_metrics(surv_tr, surv_ho, 1 - S_km[:, -1], S_km, tte.EVAL_TIMES)
na_met = survival_metrics(surv_tr, surv_ho, 1 - S_na[:, -1], S_na, tte.EVAL_TIMES)

pd.DataFrame({
    "KM (по типам)": {"Uno-C": round(km_met["uno_c"], 3), "IBS": round(km_met["ibs"], 3)},
    "NA (по типам)": {"Uno-C": round(na_met["uno_c"], 3), "IBS": round(na_met["ibs"], 3)},
    "Discrete hazard": {"Uno-C": round(met_ho["uno_c"], 3), "IBS": round(met_ho["ibs"], 3)},
}).T