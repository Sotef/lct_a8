def _is_anomaly(wk: int) -> bool:
    return du.week_is_campaign(int(wk))

at = pd.read_csv(du.find_dataset_dir() / "weekly_alarms_by_type.csv",
                 dtype={"год_неделя": int})
anom = at["год_неделя"].map(_is_anomaly)
impact = at.groupby("тип_датчика").apply(
    lambda g: pd.Series({
        "всего": g["тревог"].sum(),
        "аномально": g.loc[g["год_неделя"].map(_is_anomaly), "тревог"].sum(),
    }), include_groups=False).reset_index()
impact["доля_аном_%"] = (100 * impact["аномально"] / impact["всего"]).round(1)
impact = impact.sort_values("аномально", ascending=False)

print("Влияние аномальных недель по типам (топ-15):")
print(impact.head(15).to_string(index=False))

print("\nВывод: критично затронут Дым (доля > 80%); остальные < 5% → фон.")
fault_types = impact[impact["доля_аном_%"] > 5]["тип_датчика"].tolist()
print("Типы, требующие нейтрализации:", fault_types)