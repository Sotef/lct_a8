# Стадия 4. Сырые посуточные объектные агрегаты по годам
# → dataset/_obj_raw/_obj_raw_<год>.csv (все каналы объектов с WEAR-оборудованием)
if REBUILD:
    rawdir = DATASET / "_obj_raw"
    rawdir.mkdir(exist_ok=True)
    ref_ch = du.load_ref_channels()[["ид_канала_данных", "тип_датчика", "ид_объект"]]
    ref_ch = ref_ch.dropna(subset=["ид_объект"])
    wear_ch = ref_ch[ref_ch["тип_датчика"].isin(fe.WEAR_TYPES)]
    obj_set = set(wear_ch["ид_объект"])
    ch_all = ref_ch[ref_ch["ид_объект"].isin(obj_set)]
    obj_map = dict(zip(ch_all["ид_канала_данных"], ch_all["ид_объект"]))
    ch_set = set(ch_all["ид_канала_данных"])
    prom_ch = set(wear_ch["ид_канала_данных"])
    for year in map(str, range(2019, 2027)):
        out = rawdir / f"_obj_raw_{year}.csv"
        if out.exists():
            print(year, "skip")
            continue
        agg = fe._aggregate_object_year(year, ch_set, obj_map, prom_ch,
                                        fe.FAULT_STATUSES, fe.NOISE_VALUES)
        agg.to_csv(out, index=False, encoding="utf-8-sig")
        print(year, "OK, строк:", len(agg))
else:
    print("REBUILD=False — сырые объектные агрегаты пропущены")