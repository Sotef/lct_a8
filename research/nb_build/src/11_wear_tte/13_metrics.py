surv_tr = tte.make_surv_struct(tr_sub["event_flag"], tr_sub["obs_days"])
surv_va = tte.make_surv_struct(va_sub["event_flag"], va_sub["obs_days"])
surv_ho = tte.make_surv_struct(ho_sub["event_flag"], ho_sub["obs_days"])
risk_va = 1 - S_va[:, -1]
risk_ho = 1 - S_ho[:, -1]

def fmt(d):
    return {"Uno-C": round(d["uno_c"], 3),
            "meanAUC": round(d["mean_auc"], 3),
            "IBS": round(d["ibs"], 3)}

met_val = survival_metrics(surv_tr, surv_va, risk_va, S_va, tte.EVAL_TIMES)
met_ho = survival_metrics(surv_tr, surv_ho, risk_ho, S_ho, tte.EVAL_TIMES)
pd.DataFrame({
    "val (2025H1)": fmt(met_val),
    "holdout (2025H2+2026)": fmt(met_ho),
}).T

print("AUC по времени (holdout):", met_ho["auc_by_t"])
print("Brier по времени (holdout):", met_ho["brier"])