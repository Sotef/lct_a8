# Итог по объединённой holdout-выборке (локальные по своим объектам vs глобальная)
print("Параметры обучения локальных: iters=%s cap=%s" % (summ["params"]["iters"], summ["params"]["cap"]))
print("Число объектов в эксперименте:", len(df))
print("Объединённая выборка holdout: ЛОКАЛЬНЫЕ vs ГЛОБАЛЬНАЯ")
print(pd.DataFrame({
    "Uno-C": [summ["union"]["local"]["uno_c"], summ["union"]["global"]["uno_c"]],
    "meanAUC": [summ["union"]["local"]["mean_auc"], summ["union"]["global"]["mean_auc"]],
    "IBS": [summ["union"]["local"]["ibs"], summ["union"]["global"]["ibs"]],
}, index=["локальные", "глобальная"]).round(3).T.to_string())

print("\nПобедитель (на объединённой выборке):",
      "глобальная" if summ["union"]["global"]["uno_c"] >= summ["union"]["local"]["uno_c"]
      else "локальные")