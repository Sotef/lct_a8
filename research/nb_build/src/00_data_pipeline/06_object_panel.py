# Стадия 5. Объектный контекст (дни, окна, доли, z-скор, статика)
# → dataset/daily_panel_object_context.csv
if REBUILD:
    obj = fe.make_object_panel(recompute=True)
    print("объектный контекст (пересобран):", obj.shape)
else:
    try:
        import pandas as pd
        obj = pd.read_csv(DATASET / "daily_panel_object_context.csv",
                          dtype={"ид_объект": str})
        print("объектный контекст (кэш):", obj.shape)
    except FileNotFoundError:
        print("объектный контекст не найден; поставьте REBUILD = True")