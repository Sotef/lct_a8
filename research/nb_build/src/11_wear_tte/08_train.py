# Discrete-time hazard: CatBoost(Logloss) на person-time.
# Early stopping по logloss на внутренней валидации (<= 2025-06-30).
m = fit_discrete_hazard(X_tr, y_tr, X_va, y_va, iters=CFG["iters"],
                        lr=CFG["lr"], depth=CFG["depth"], seed=CFG["seed"])
print("лучшая итерация:", m.get_best_iteration())
out_dir = RESEARCH / "models"
out_dir.mkdir(exist_ok=True)
m.save_model(out_dir / "tte_discrete_hazard.cbm")
print("model saved ->", out_dir / "tte_discrete_hazard.cbm")