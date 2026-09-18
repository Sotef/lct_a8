# Только для первого прогона (если панели нет) — RECOMPUTE=True пересчитает.
# Здесь оставляем RECOMPUTE=False: если артефакт уже построен — просто читаем.
panel = fe.make_daily_panel(types=fe.WEAR_TYPES, recompute=RECOMPUTE)
# Контекст объекта: все каналы объекта (дым, газ, температура, соседние насосы
# и т.д.) за день и окна 3/7/14/30д + композитные признаки «соседей».
panel = fe.add_object_context(panel, recompute=RECOMPUTE)
print("\nПанель:", panel.shape)
print("Колонок всего:", panel.shape[1])
print("Колонки:", list(panel.columns))
print("\nЦелевая доля (по чистым дням): %.3f%%" % (panel["цель_24ч"].mean() * 100))
print(panel["цель_24ч"].value_counts(dropna=False).to_dict())
panel.head()