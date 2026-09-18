# Таблица результатов по объектам (локальная vs глобальная на одних holdout-субъектах)
cols = ["объект", "n_train", "n_holdout", "ho_событий",
        "uno_c_лок", "uno_c_глоб", "auc_лок", "auc_глоб",
        "ibs_лок", "ibs_глоб", "pr24_лок", "pr24_глоб"]
df[cols].round(3).to_string(index=False)