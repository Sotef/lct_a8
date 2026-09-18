import torch

print("torch CUDA:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))

# CatBoost GPU — НЕ используем в этом ноутбуке:
# собственный тест падает с CUDA OOM даже на 500x6 (известный баг выделения
# в CatBoost); CPU-версия даёт тот же результат ~0.90.
print("CatBoost: только CPU (GPU-бэкенд даёт CUDA OOM)")

# XGBoost GPU
import xgboost as xgb
Xg = pd.DataFrame(np.random.rand(500, 6))
try:
    m = xgb.XGBClassifier(tree_method="hist", device="cuda", n_estimators=5, verbosity=0)
    m.fit(Xg.astype("float32"), (np.random.rand(500) > 0.5).astype(int))
    print("XGBoost GPU: OK")
except Exception as e:
    print("XGBoost GPU: FAIL —", str(e)[:80])

# LightGBM GPU
import lightgbm as lgb
try:
    m = lgb.LGBMClassifier(device="gpu", n_estimators=5, verbose=-1)
    m.fit(Xg, (np.random.rand(500) > 0.5).astype(int))
    print("LightGBM GPU: OK")
except Exception as e:
    print("LightGBM GPU: FAIL —", str(e)[:100])