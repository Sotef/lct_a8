# Стадия 3. Финальный 6-часовой панель (окна 12ч..30д, z-скор, сезонность,
# цели 6ч/12ч/24ч/48ч, контекст объекта) → dataset/subdaily_panel_wear_6h.csv
panel = fe.make_subdaily_panel(recompute=REBUILD)
print("панель:", panel.shape)