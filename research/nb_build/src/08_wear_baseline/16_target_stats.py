# Статистика таргета (по train/val/test после исключения кампаний)
from sklearn.metrics import precision_score as ps, recall_score as rs

print("Целевая переменная: цель_24ч (бинарная, статус неисправности в +24ч)")
for name, dfx in [("train", train), ("val", val), ("test", test)]:
    yv = dfx[y_col]
    print(f"  {name}: n={len(yv):,} | pos={yv.sum():,} ({100*yv.mean():.2f}%) "
          f"| neg={(~yv.astype(bool)).sum():,}")

# «Всегда 1» и «всегда 0» — тривиальные baseline
print("\nBaseline 'всегда 1': precision=%.3f recall=1.000" %
      (test[y_col].mean()))
print("Baseline 'всегда 0': precision=0 recall=0.000")