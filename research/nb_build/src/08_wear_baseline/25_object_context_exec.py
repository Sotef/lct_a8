# Диагностика: насколько объектный контекст информативен для таргета
obj_cols = [c for c in panel.columns if c.endswith("_об") or "_соседей_" in c
            or c.startswith(("n_каналов", "доля_", "z_объект"))]
obj_cols = [c for c in obj_cols if c in panel.columns and c not in drop_cols]
print("Колонок контекста объекта:", len(obj_cols))
print("\n".join(f"  {c}" for c in obj_cols))

# Корреляция контекста с таргетом на train (вне кампаний)
corr_y = (train[obj_cols + [y_col]].corr()[y_col].drop(labels=[y_col])
          .sort_values(key=abs, ascending=False))
print("\nКорреляция контекста объекта с целью (Pearson, train):")
print(corr_y.round(3).to_string())
print("\n(Линейная корреляция — верхняя оценка; бустинг ловит и нелинейные "
      "взаимодействия канал×объект.)")