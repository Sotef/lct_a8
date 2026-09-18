panel = fe.make_subdaily_panel(recompute=RECOMPUTE)
panel = fe.add_series_targets(panel)

# Ор-динальные классы «дней до события» (для второго слоя)
BINS_DAYS = [0.5, 1, 2, 3, 7, 14, 30]
MID = np.array([0.25, 0.75, 1.5, 2.5, 5.0, 10.5, 22.0, 45.0])
panel["дни_класс"] = np.clip(np.digitize(panel["дни_до_серии"], BINS_DAYS), 0, len(BINS_DAYS))
panel["дни_класс"] = panel["дни_класс"].fillna(len(BINS_DAYS)).astype(int)  # цензур -> «>30д»

print("Суб-суточный панэль:", panel.shape)
print(f"неисправных бакетов: {(panel['неисправностей'] > 0).sum():,} | "
      f"стартов серий (событий): {int(panel['серия_старт'].sum()):,} "
      f"({100 * panel['серия_старт'].mean():.2f}% строк)")
print("\nБаза новых событий (цель_серии_*, чистые дни):")
for n in fe.HORIZONS:
    y = panel[f"цель_серии_{n}"].dropna()
    print(f"  цель_серии_{n}: {100 * y.mean():6.3f}%")
d = panel["дни_до_серии"].dropna()
print(f"\nдней до след. события: медиана {np.median(d):.1f}, "
      f"q25 {np.quantile(d, .25):.1f}, q75 {np.quantile(d, .75):.1f}; "
      f"цензурировано {100 * panel['дни_до_серии'].isna().mean():.2f}%")
print("\nраспределение дней_класс:")
print(panel["дни_класс"].value_counts().sort_index().rename_axis("класс").to_string())