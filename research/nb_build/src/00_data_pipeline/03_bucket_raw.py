# Стадия 2. Сырые 6-часовые агрегаты WEAR-каналов по годам
# → dataset/_buckets_raw/_buckets_raw_<год>.csv
if REBUILD:
    rawdir = DATASET / "_buckets_raw"
    rawdir.mkdir(exist_ok=True)
    ref_ch = du.load_ref_channels()[["ид_канала_данных", "тип_датчика", "ид_объект"]]
    ref_ch = ref_ch.dropna(subset=["ид_объект"])
    ch_set = set(ref_ch.loc[ref_ch["тип_датчика"].isin(fe.WEAR_TYPES), "ид_канала_данных"])
    for year in map(str, range(2019, 2027)):
        out = rawdir / f"_buckets_raw_{year}.csv"
        if out.exists():
            print(year, "skip")
            continue
        agg = fe._aggregate_bucket_year(year, ch_set, fe.FAULT_STATUSES, fe.NOISE_VALUES)
        agg.to_csv(out, index=False, encoding="utf-8-sig")
        print(year, "OK, строк:", len(agg))
else:
    print("REBUILD=False — сырые 6ч-агрегаты пропущены")