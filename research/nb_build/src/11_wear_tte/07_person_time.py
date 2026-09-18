# Развёртка в person-time: каждая строка = (субъект, шаг t), метка = событие в шаге.
# Фичи субъекта заморожены на t0; добавляются признаки шага (шаг, час, д.н., месяц).
X_tr, y_tr = tte.expand_person_time(tr_sub, X_cols, tte.HORIZON_BUCKETS)
X_va, y_va = tte.expand_person_time(va_sub, X_cols, tte.HORIZON_BUCKETS)
print("train person-time:", X_tr.shape, "| val:", X_va.shape)
print("доля «событие в шаге»: %.3f%%" % (100 * y_tr.mean()))
X_tr.head(3)