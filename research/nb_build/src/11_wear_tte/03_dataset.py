# Таблица субъектов (канал x 6ч-бакет): цель = дни до следующего старта серии.
# Строится один раз и кэшируется в dataset/tte_subjects.parquet.
subjects = build_dataset()
print("строк:", f"{subjects.shape[0]:,}", "| колонок:", subjects.shape[1])
print("событие в 30д: %.1f%% | медиана obs: %.1f дн | цензур: %.1f%%" % (
    subjects["event_flag"].mean() * 100, subjects["obs_days"].median(),
    100 * (1 - subjects["event_flag"].mean())))