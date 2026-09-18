from pathlib import Path

# Какие типы обрабатываем (первый прогон — дым, самый пострадавший)
TARGET_TYPES = ["Датчик дыма"]
FAULT_STATUSES = {"Неисправен", "Обесточен", "Отключено устройство"}
YEARS_ALL = list(map(str, range(2019, 2027)))
DATASET = du.find_dataset_dir()
CHUNK = 1_000_000


def build_daily_for_type(typ: str, years, out_csv: Path, compute_median: bool = False):
    """Суточные агрегаты (канал × дата) для одного типа датчиков.

    Векторно: по чанку делаем groupby(канал, дата).agg(...), кусочки года
    копим в список, в конце года пишем CSV. Пик памяти ~ размер года.
    """
    ref_ch = du.load_ref_channels()[["ид_канала_данных", "тип_датчика"]]
    ch_set = set(ref_ch.loc[ref_ch["тип_датчика"] == typ, "ид_канала_данных"])

    year_files = []
    for fp in du.journal_files():
        year = fp.name.split("-")[2].split(".")[0]
        if year not in years:
            continue
        year_parts = []
        for ch in du.read_chunks(fp,
                                 cols=["ид_канала_данных", "дата", "тревожное", "значение_датчика"],
                                 chunksize=CHUNK):
            m = ch["ид_канала_данных"].isin(ch_set)
            if not m.any():
                continue
            ch = ch[m]
            g = ch.groupby(["ид_канала_данных", "дата"], sort=False)
            agg = pd.DataFrame({
                "событий": g.size(),
                "тревог": g["тревожное"].apply(lambda s: (s == "t").sum()),
                "неисправностей": g["значение_датчика"].apply(
                    lambda s: s.isin(FAULT_STATUSES).sum()),
                "шума": g["значение_датчика"].apply(
                    lambda s: s.isin(["0.00", "0.01", "0.02"]).sum()),
            }).reset_index()
            if compute_median:
                vals = ch.assign(vnum=pd.to_numeric(
                    ch["значение_датчика"].str.replace(",", "."), errors="coerce"))
                med = (vals.groupby(["ид_канала_данных", "дата"])["vnum"]
                           .median().rename("медиана_знач"))
                agg = agg.merge(med, on=["ид_канала_данных", "дата"], how="left")
            year_parts.append(agg)
        pdf = pd.concat(year_parts, ignore_index=True)
        yf = out_csv.with_name(f"daily_agg_{typ.split()[-1]}_{year}.csv")
        pdf.to_csv(yf, index=False, encoding="utf-8-sig")
        year_files.append(yf)
        del year_parts, pdf
        print(f"[{typ}::{year}] ок, строк={pd.read_csv(yf).shape[0]:,}")

    # объединение годовых файлов
    df = pd.concat([pd.read_csv(f, dtype={"ид_канала_данных": str, "дата": str})
                    for f in year_files], ignore_index=True)
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"[{typ}] панель: {out_csv.name}, строк: {len(df):,}")

for typ in TARGET_TYPES:
    key = "дым" if "дым" in typ.lower() else typ.replace(" ", "_").lower()
    out_csv = DATASET / f"daily_agg_{YEARS_ALL[0]}_{YEARS_ALL[-1]}_{key}.csv"
    if RECOMPUTE or not out_csv.exists():
        build_daily_for_type(typ, YEARS_ALL, out_csv,
                             compute_median=("температура" in typ.lower()))
    else:
        print("артефакт уже есть:", out_csv.name)