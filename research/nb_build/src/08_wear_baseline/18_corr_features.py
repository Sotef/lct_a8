import matplotlib.pyplot as plt
import seaborn as sns

# Корреляция на train (убираем лейбл-коды объектов из-за номогенной природы)
corr_cols = [c for c in X_cols if not c.endswith("_code")]
cmat = train[corr_cols + [y_col]].corr()

# 1) Матрица признаков × признаков (кластеризованная тепловая карта)
plt.figure(figsize=(11, 9))
sns.heatmap(cmat[corr_cols].drop(columns=[y_col], errors="ignore"),
            cmap="RdBu_r", center=0, vmin=-1, vmax=1, annot=False,
            linewidths=0.4)
plt.title("Корреляция признаков между собой (Pearson, train)")
plt.tight_layout()
plt.show()

# Пара признаков с самой высокой |корреляцией| (подозрительные дубли)
c = cmat[corr_cols].drop(columns=[y_col], errors="ignore")
todrop = []
for i in range(len(c.columns)):
    for j in range(i + 1, len(c.columns)):
        a, b = c.columns[i], c.columns[j]
        if abs(c.loc[a, b]) > 0.95:
            todrop.append((a, b, round(c.loc[a, b], 3)))
print("Пары с |corr|>0.95 (кандидаты на удаление):")
for t in sorted(todrop, key=lambda x: -abs(x[2])):
    print("  ", t)