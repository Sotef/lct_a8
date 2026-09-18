import warnings
warnings.filterwarnings("ignore")
from sklearn.metrics import precision_recall_curve, average_precision_score, precision_score, recall_score, f1_score

# ПАРАМЕТРЫ baseline (общее для всех глобальных моделей)
GLOBAL_ITERS = 3000
LR = 0.03
DEPTH_G = 7
ES_ROUNDS = 400

# LightGBM (CPU) — оптимизация F1 (early stopping на val) через lgb.train
import lightgbm as lgb
from sklearn.metrics import f1_score


def _lgb_f1(preds, ds):
    yt = ds.get_label()
    return "f1", f1_score(yt, (preds >= 0.5).astype(int), zero_division=0), True


_lgb_dt = lgb.Dataset(train[X_cols], label=train[y_col])
_lgb_dv = lgb.Dataset(val[X_cols], label=val[y_col], reference=_lgb_dt)
lgb_params = dict(objective="binary", learning_rate=LR, max_depth=DEPTH_G,
                  num_leaves=63, is_unbalance=True, num_threads=8, verbose=-1)
lgbm = lgb.train(lgb_params, _lgb_dt, num_boost_round=GLOBAL_ITERS,
                 valid_sets=[_lgb_dv], valid_names=["val"], feval=_lgb_f1,
                 callbacks=[lgb.early_stopping(ES_ROUNDS, verbose=False)])
print("LGBM train done (iters:", lgbm.best_iteration, ")")

# XGBoost (GPU) — F1 через custom_metric (низкоуровневый train, ES по F1)
import xgboost as xgb
from sklearn.metrics import f1_score


def _f1_metric(predt, dtrain):
    yt = dtrain.get_label()
    yp = (predt >= 0.5).astype(int)
    return "f1", f1_score(yt, yp, zero_division=0)


_dm_train = xgb.DMatrix(train[X_cols].astype("float32"), label=train[y_col])
_dm_val = xgb.DMatrix(val[X_cols].astype("float32"), label=val[y_col])
_dm_test = xgb.DMatrix(test[X_cols].astype("float32"))
xgb_params = dict(
    max_depth=DEPTH_G, eta=LR, objective="binary:logistic",
    tree_method="hist", device="cuda", nthread=1, seed=42,
    scale_pos_weight=sum(train[y_col] == 0) / max(sum(train[y_col] == 1), 1),
)
xgbm = xgb.train(
    xgb_params, _dm_train, num_boost_round=GLOBAL_ITERS,
    evals=[(_dm_val, "val")], custom_metric=_f1_metric, maximize=True,
    early_stopping_rounds=ES_ROUNDS, verbose_eval=False)
print("XGB train done (iters:", xgbm.best_iteration, ")")

# CatBoost (CPU) — F1 встроенная
from catboost import CatBoostClassifier, Pool
catb = CatBoostClassifier(
    iterations=GLOBAL_ITERS, learning_rate=LR, depth=DEPTH_G,
    l2_leaf_reg=3, random_seed=42, task_type="CPU",
    eval_metric="F1", early_stopping_rounds=ES_ROUNDS, verbose=200)
catb.fit(Pool(train[X_cols], train[y_col]),
         eval_set=Pool(val[X_cols], val[y_col]))
print("CatBoost train done (iters:", catb.get_best_iteration(), ")")