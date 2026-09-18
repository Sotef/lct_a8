out_csv = du.find_dataset_dir() / "weekly_summary.csv"
out_al = du.find_dataset_dir() / "weekly_alarms_by_type.csv"

if RECOMPUTE or not out_csv.exists():
    ref_ch = du.load_ref_channels()[["ид_канала_данных", "тип_датчика"]]

    # Аккумуляторы: простые pandas-агрегаты по чанкам
    acc = []          # (год_неделя, событий, тревог, каналов)
    acc_al = []       # (год_неделя, тип_датчика, тревог)

    for fp in du.journal_files():
        year = fp.name.split("-")[2].split(".")[0]
        for ch in du.read_chunks(fp, cols=["дата", "тревожное", "ид_канала_данных"]):
            dt = pd.to_datetime(ch["дата"])
            iso = dt.dt.isocalendar()
            wk = iso["year"].astype("int64") * 100 + iso["week"].astype("int64")

            g = (ch.assign(wk=wk, alarm=ch["тревожное"].eq("t"))
                   .groupby("wk", sort=False))
            s = g["alarm"].size().rename("событий")
            a = g["alarm"].sum().astype("int64").rename("тревог")
            c = g["ид_канала_данных"].nunique().rename("каналов")
            acc.append(pd.concat([s, a, c], axis=1).reset_index())

            # тревоги по типам датчиков
            al = ch[ch["тревожное"].eq("t")]
            if len(al):
                typ = al["ид_канала_данных"].map(dict(zip(ref_ch["ид_канала_данных"],
                                                          ref_ch["тип_датчика"]))
                                                 ).fillna("(нет в справочнике)")
                tmp = pd.DataFrame({
                    "wk": wk.loc[al.index],
                    "тип_датчика": typ,
                    "alarm": 1,
                })
                g2 = tmp.groupby(["wk", "тип_датчика"], sort=False)["alarm"].sum().rename("тревог")
                acc_al.append(g2.reset_index())
        print(f"[{year}] done, недель в акк: {sum(x['wk'].nunique() for x in acc)}", flush=True)

    weekly = pd.concat(acc).groupby("wk", as_index=False).sum(numeric_only=True)
    weekly.columns = ["год_неделя", "событий", "тревог", "каналов"]
    weekly["год"] = (weekly["год_неделя"] // 100).astype(int)
    weekly["неделя"] = (weekly["год_неделя"] % 100).astype(int)
    weekly["доля_тревог_%"] = (100 * weekly["тревог"] / weekly["событий"]).round(4)
    weekly = weekly.sort_values("год_неделя").reset_index(drop=True)
    weekly.to_csv(out_csv, index=False, encoding="utf-8-sig")

    at = pd.concat(acc_al).groupby(["wk", "тип_датчика"], as_index=False)["тревог"].sum()
    at = at.rename(columns={"wk": "год_неделя"})
    at.to_csv(out_al, index=False, encoding="utf-8-sig")
else:
    weekly = pd.read_csv(out_csv, dtype={"год_неделя": str, "год": str, "неделя": str})
    at = pd.read_csv(out_al, dtype={"год_неделя": str})
    print("Прочитано из готовых артефактов")

print("Недель всего:", len(weekly))
weekly.head(10)