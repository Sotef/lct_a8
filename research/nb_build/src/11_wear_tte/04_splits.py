# Временной сплит + проверка честности (ни одна метка не пересекает границу холдаута)
train, val, holdout = tte.split_subjects(subjects)
verify_no_lookup(train, val, holdout)

rows = []
for name, s in (("train", train), ("val", val), ("holdout", holdout)):
    rows.append({"сплит": name,
                 "строк": f"{len(s):,}",
                 "событий, %": round(100 * s["event_flag"].mean(), 1),
                 "медиана obs, дн": round(s["obs_days"].median(), 1),
                 "цензур, %": round(100 * (1 - s["event_flag"].mean()), 1)})
pd.DataFrame(rows)