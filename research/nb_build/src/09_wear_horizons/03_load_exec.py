panel = fe.make_subdaily_panel(recompute=RECOMPUTE)
print("Суб-суточный панэль:", panel.shape)
print("Колонки:", list(panel.columns))
print("\nДоля целевых переменных (чистые дни, без кампаний):")
for name in fe.HORIZONS:
    y = panel[f"цель_{name}"].dropna()
    print(f"  цель_{name}: {100 * y.mean():6.3f}% положительных  (n={len(y):,})")
panel.head()