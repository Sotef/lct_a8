# Сбалансированные выборки субъектов: старты серий / неисправные не-старты / прочее
tr_sub = tte.sample_subjects(train, CFG["n_starts"], CFG["n_fault"],
                             CFG["n_nonfault"], seed=CFG["seed"])
va_sub = tte.sample_subjects(val, CFG["n_val"] // 3, CFG["n_val"] // 3,
                             CFG["n_val"] // 3, seed=CFG["seed"] + 1)
ho_sub = tte.sample_holdout(holdout, CFG["n_hold"], seed=777)
print("train:", len(tr_sub), "| val:", len(va_sub), "| holdout:", len(ho_sub))
print("событий в 30д: train %.1f%% | val %.1f%% | holdout %.1f%%" % (
    100 * tr_sub["event_flag"].mean(), 100 * va_sub["event_flag"].mean(),
    100 * ho_sub["event_flag"].mean()))