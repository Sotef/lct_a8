# Кривые выживаемости для внутренней валидации и холдаута: S(t), t = 1..120 (6ч..30д)
S_va = predict_survival_discrete(m, va_sub, X_cols)
S_ho = predict_survival_discrete(m, ho_sub, X_cols)
print("S val:", S_va.shape, "| S holdout:", S_ho.shape)
print("средний риск 30д (holdout): %.3f (наблюдаемый: %.3f)" % (
    1 - S_ho[:, -1].mean(), ho_sub["event_flag"].mean()))