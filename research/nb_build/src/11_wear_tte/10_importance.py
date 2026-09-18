step_names = ["шаг", "час_шага", "день_недели_шага", "месяц_шага", "доля_горизонта"]
imp = pd.Series(m.get_feature_importance(type="PredictionValuesChange"),
                index=X_cols + step_names)
top = imp.sort_values(ascending=False).head(15)
fig, ax = plt.subplots(figsize=(7, 5))
top.iloc[::-1].plot.barh(ax=ax, color="steelblue")
ax.set_title("Важность фич в hazard-модели (PredictionValuesChange)")
ax.set_xlabel("importance")
plt.tight_layout()
plt.show()