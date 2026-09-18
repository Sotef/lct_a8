# -*- coding: utf-8 -*-
"""Feature pipeline: панель «канал x день» для обучения.

Фичи: счётчики событий/тревог/неисправностей/шума за 3/7/14/30 дней
(rolling по каналу), z-скор частоты события, сезонные признаки
(неделя года, день года, месяц, день недели).
Цель: цель_24ч — неисправность в следующие 24 часа.
Аномальные недели (кампании) помечаются и исключаются из разметки (NaN).
"""
from __future__ import annotations

import pathlib
from typing import Iterable, Optional

import numpy as np
import pandas as pd

import data_utils as du

DATASET = du.find_dataset_dir()

FAULT_STATUSES = {"Неисправен", "Обесточен", "Отключено устройство", "Затоплен"}
NOISE_VALUES = {"0.00", "0.01", "0.02"}

WEAR_TYPES = ["Состояние насоса", "Состояние вентилятора", "Состояние фазы"]

_BASE_FEATS = ["событий", "тревог", "неисправностей", "шума"]
_DROP_COLS = ["ид_канала_данных", "дата", "год_неделя", "аномально", "цель_24ч"]

# --- Суб-суточный (6-часовой) панэль и горизонты прогноза ------------------
BUCKET_HOURS = 6          # длина бакета в часах (4 бакета в сутках)
BUCKET_WINDOWS = (2, 4, 8, 28, 120)   # календарные окна: 12ч, 24ч, 48ч, 7д, 30д
HORIZONS = {"6ч": 1, "12ч": 2, "24ч": 4, "48ч": 8}   # цель = неисправность в ближайшие N бакетов
SERIES_GAP = 4     # разрыв серии в бакетах (24 ч): если неисправность не была >=24ч — это та же серия
_BUCKET_RAW_DIR = DATASET / "_buckets_raw"


def make_daily_panel(
    types: Iterable[str],
    years: Optional[Iterable[str]] = None,
    fault_statuses: Optional[set] = None,
    noise_values: Optional[set] = None,
    out_csv: Optional[pathlib.Path] = None,
    recompute: bool = False,
) -> pd.DataFrame:
    """Суточная панель (канал x дата) для перечня типов датчиков."""
    types = list(types)
    years = list(years) if years is not None else list(map(str, range(2019, 2027)))
    if fault_statuses is None:
        fault_statuses = FAULT_STATUSES
    if noise_values is None:
        noise_values = NOISE_VALUES
    key = "_".join(t.replace(" ", "_") for t in types)
    if out_csv is None:
        out_csv = DATASET / f"daily_panel_{key}.csv"
    if not recompute and out_csv.exists():
        return pd.read_csv(out_csv, dtype={"ид_канала_данных": str, "дата": str})

    ref_ch = du.load_ref_channels()[["ид_канала_данных", "тип_датчика", "ид_объект"]]
    ch_set = set(ref_ch.loc[ref_ch["тип_датчика"].isin(types), "ид_канала_данных"])
    obj_map = dict(zip(ref_ch["ид_канала_данных"], ref_ch["ид_объект"]))
    year_parts = []
    for fp in du.journal_files():
        year = fp.name.split("-")[2].split(".")[0]
        if year not in years:
            continue
        parts = []
        for ch in du.read_chunks(fp, cols=["ид_канала_данных", "дата", "тревожное", "значение_датчика"]):
            m = ch["ид_канала_данных"].isin(ch_set)
            if not m.any():
                continue
            ch = ch[m]
            g = ch.groupby(["ид_канала_данных", "дата"], sort=False)
            agg = pd.DataFrame({
                "событий": g.size(),
                "тревог": g["тревожное"].apply(lambda s: (s == "t").sum()),
                "неисправностей": g["значение_датчика"].apply(
                    lambda s: s.isin(fault_statuses).sum()),
                "шума": g["значение_датчика"].apply(
                    lambda s: s.isin(noise_values).sum()),
            }).reset_index()
            parts.append(agg)
        if parts:
            year_parts.append(pd.concat(parts, ignore_index=True))
    df = pd.concat(year_parts, ignore_index=True)
    df["ид_объект"] = df["ид_канала_данных"].map(obj_map).astype("Int64")
    dt = pd.to_datetime(df["дата"])
    iso = dt.dt.isocalendar()
    df["неделя_года"] = iso["week"].astype(int)
    df["день_года"] = dt.dt.dayofyear
    df["месяц"] = dt.dt.month
    df["день_недели"] = dt.dt.dayofweek
    df["год_неделя"] = iso["year"].astype(int) * 100 + iso["week"].astype(int)
    df["аномально"] = df["год_неделя"].map(du.week_is_campaign)

    df = df.sort_values(["ид_канала_данных", "дата"]).reset_index(drop=True)
    grp = df.groupby("ид_канала_данных", sort=False)
    for w in (3, 7, 14, 30):
        df[f"событий_{w}д"] = grp["событий"].transform(lambda s: s.rolling(w, min_periods=1).sum())
        df[f"неисправностей_{w}д"] = grp["неисправностей"].transform(lambda s: s.rolling(w, min_periods=1).sum())
        df[f"тревог_{w}д"] = grp["тревог"].transform(lambda s: s.rolling(w, min_periods=1).sum())

    clean = df[~df["аномально"]]
    ch_med = clean.groupby("ид_канала_данных")[_BASE_FEATS].median()
    df[_BASE_FEATS] = df[_BASE_FEATS].astype(float)
    ch_med_map = ch_med.reindex(df["ид_канала_данных"].unique()).fillna(
        clean[_BASE_FEATS].median())
    vals = ch_med_map.loc[df["ид_канала_данных"].values].values
    df.loc[df["аномально"].values, _BASE_FEATS] = vals[df["аномально"].values]

    ch_med_ev = clean.groupby("ид_канала_данных")["событий"].median()
    ch_iqr = clean.groupby("ид_канала_данных")["событий"].quantile(0.75) - \
             clean.groupby("ид_канала_данных")["событий"].quantile(0.25)
    df["z_событий"] = (df["событий"] - df["ид_канала_данных"].map(ch_med_ev)) / \
                      (df["ид_канала_данных"].map(ch_iqr) + 1e-6)

    df = df.sort_values(["ид_канала_данных", "дата"]).reset_index(drop=True)
    grp_t = df.groupby("ид_канала_данных", sort=False)
    df["цель_24ч"] = grp_t["неисправностей"].transform(
        lambda s: s.shift(-1).fillna(0).gt(0).astype(int))
    df.loc[df["аномально"], "цель_24ч"] = np.nan

    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"Панель сохранена: {out_csv.name}, строк: {len(df):,}")
    return df


# ---------------------------------------------------------------------------
# Контекст объекта: агрегация по ВСЕМ каналам объекта за день/окна 3/7/14/30д
# ---------------------------------------------------------------------------
# Каждая строка канал×день дополняется тем, что происходит у «соседей»: все
# каналы объекта (насосы, вентиляторы, фазы, дым, газ, температура, двери…),
# отдельно — «промышленные» WEAR-каналы. Плюс композитные признаки
# «соседних» каналов (без собственного вклада канала), чтобы не дублировать
# пер-канальные фичи и не подменять таргет.


def _aggregate_object_year(year: str, ch_set, obj_map, prom_ch,
                           fault_statuses: set, noise_values: set) -> pd.DataFrame:
    """Агрегирует события по ВСЕМ каналам объектов за один год -> (объект, дата).

    Двухступенчато: (1) суточные счётчики по каналам с дедупликацией границ
    чанков, (2) свёртка в объект×день (суммы + nunique каналов). Так год
    держится в памяти без OOM (сырая выборка в 2021 ~41 млн строк).
    Возвращает колонки: _объект, дата, событий_об, тревог_об, неисправностей_об,
    шума_об, каналов_активных_об, каналы_неисправны_об, неисправностей_пром_об,
    каналы_пром_неисправны_об.
    """
    cols = ["_объект", "дата", "событий_об", "тревог_об", "неисправностей_об",
            "шума_об", "каналов_активных_об", "каналы_неисправны_об",
            "неисправностей_пром_об", "каналы_пром_неисправны_об"]
    for fp in du.journal_files():
        if fp.name.split("-")[2].split(".")[0] != year:
            continue
        rows: list[pd.DataFrame] = []
        for ch in du.read_chunks(fp, cols=["ид_канала_данных", "дата", "тревожное", "значение_датчика"]):
            m = ch["ид_канала_данных"].isin(ch_set)
            if not m.any():
                continue
            ch = ch[m].copy()
            ch["_неиспр"] = ch["значение_датчика"].isin(fault_statuses)
            ch["_шум"] = ch["значение_датчика"].isin(noise_values)
            ch["_трев"] = ch["тревожное"].eq("t")
            chd = ch.groupby(["ид_канала_данных", "дата"], sort=False).agg(
                n_событий=("ид_канала_данных", "size"),
                n_тревог=("_трев", "sum"),
                n_неиспр=("_неиспр", "sum"),
                n_шум=("_шум", "sum"),
            ).reset_index()
            rows.append(chd)
        if not rows:
            return pd.DataFrame(columns=cols)
        chd = pd.concat(rows, ignore_index=True)
        # Дедупликация (канал, дата): события дня могут попасть в два чанка
        chd = chd.groupby(["ид_канала_данных", "дата"], sort=False) \
                 .sum(numeric_only=True).reset_index()
        chd["_объект"] = chd["ид_канала_данных"].map(obj_map)
        chd["_пром"] = chd["ид_канала_данных"].isin(prom_ch)

        g = chd.groupby(["_объект", "дата"], sort=False)
        agg = g.agg(
            событий_об=("n_событий", "sum"),
            тревог_об=("n_тревог", "sum"),
            неисправностей_об=("n_неиспр", "sum"),
            шума_об=("n_шум", "sum"),
            каналов_активных_об=("ид_канала_данных", "nunique"),
        ).reset_index()
        d = chd[chd["n_неиспр"] > 0]
        if len(d):
            gg = d.groupby(["_объект", "дата"], sort=False)["ид_канала_данных"] \
                  .nunique().rename("каналы_неисправны_об")
            agg = agg.merge(gg, on=["_объект", "дата"], how="left")
        else:
            agg["каналы_неисправны_об"] = 0
        p = chd[chd["_пром"]]
        if len(p):
            gp = p.groupby(["_объект", "дата"], sort=False).agg(
                неисправностей_пром_об=("n_неиспр", "sum"),
            ).reset_index()
            pu = p[p["n_неиспр"] > 0]
            if len(pu):
                gp = gp.merge(
                    pu.groupby(["_объект", "дата"], sort=False)["ид_канала_данных"]
                      .nunique().rename("каналы_пром_неисправны_об"),
                    on=["_объект", "дата"], how="left")
            else:
                gp["каналы_пром_неисправны_об"] = 0
            agg = agg.merge(gp, on=["_объект", "дата"], how="left")
        else:
            agg["неисправностей_пром_об"] = 0
            agg["каналы_пром_неисправны_об"] = 0
        agg = agg.fillna({"каналы_неисправны_об": 0, "каналы_пром_неисправны_об": 0,
                          "неисправностей_пром_об": 0})
        return agg
    return pd.DataFrame(columns=cols)


def finalize_object_panel(raw: pd.DataFrame, types: Optional[Iterable[str]] = None,
                          out_csv: Optional[pathlib.Path] = None) -> pd.DataFrame:
    """Финализация «сырой» объектной панели (объект, дата, счётчики).

    Добавляет статические размеры объекта (n_каналов…), сезонные признаки,
    rolling-окна 3/7/14/30д, нейтрализацию кампанийных недель медианой
    объекта и z-скор активности. При `out_csv` — сохраняет.
    """
    if types is None:
        types = WEAR_TYPES
    types = list(types)
    df = raw.copy()
    df = df.rename(columns={"_объект": "ид_объект"})
    df["ид_объект"] = df["ид_объект"].astype(str)

    ref_ch = du.load_ref_channels()[["ид_канала_данных", "тип_датчика", "ид_объект"]]
    ref_ch = ref_ch.dropna(subset=["ид_объект"])
    n_all = ref_ch.groupby("ид_объект")["ид_канала_данных"].nunique()
    n_prom = ref_ch[ref_ch["тип_датчика"].isin(types)] \
        .groupby("ид_объект")["ид_канала_данных"].nunique()

    # Статические размеры объекта
    df["n_каналов_об"] = df["ид_объект"].map(n_all).astype(int)
    df["n_пром_каналов_об"] = df["ид_объект"].map(n_prom).fillna(0).astype(int)
    df["доля_каналов_неисправны_день"] = df["каналы_неисправны_об"] / df["n_каналов_об"]
    df["доля_пром_каналов_неисправны_день"] = (
        df["каналы_пром_неисправны_об"] / df["n_пром_каналов_об"].replace(0, np.nan))

    # Сезонные признаки объекта (не сохраняются: они уже есть в пер-канальной
    # панели, но нужны для z-скора и флагов кампаний)
    dt = pd.to_datetime(df["дата"])
    iso = dt.dt.isocalendar()
    df["год_неделя"] = iso["year"].astype(int) * 100 + iso["week"].astype(int)
    df["аномально"] = df["год_неделя"].map(du.week_is_campaign)
    df["день_года"] = dt.dt.dayofyear
    df["месяц"] = dt.dt.month

    df = df.sort_values(["ид_объект", "дата"]).reset_index(drop=True)
    grp = df.groupby("ид_объект", sort=False)
    for w in (3, 7, 14, 30):
        df[f"неисправностей_об_{w}д"] = grp["неисправностей_об"].transform(
            lambda s: s.rolling(w, min_periods=1).sum())
    for w in (7, 30):
        df[f"событий_об_{w}д"] = grp["событий_об"].transform(
            lambda s: s.rolling(w, min_periods=1).sum())
        df[f"каналов_активных_об_{w}д"] = grp["каналов_активных_об"].transform(
            lambda s: s.rolling(w, min_periods=1).sum())
        df[f"неисправностей_пром_об_{w}д"] = grp["неисправностей_пром_об"].transform(
            lambda s: s.rolling(w, min_periods=1).sum())

    # Нейтрализация кампанийных недель — медианой объекта (как в make_daily_panel)
    base_cols = ["событий_об", "тревог_об", "неисправностей_об", "шума_об"]
    clean = df[~df["аномально"]]
    med = clean.groupby("ид_объект")[base_cols].median()
    df[base_cols] = df[base_cols].astype(float)
    med_map = med.reindex(df["ид_объект"].unique()).fillna(clean[base_cols].median())
    vals = med_map.loc[df["ид_объект"].values].values
    df.loc[df["аномально"].values, base_cols] = vals[df["аномально"].values]

    # z-скор активности объекта (по дням вне кампаний)
    med_ev = clean.groupby("ид_объект")["событий_об"].median()
    q75 = clean.groupby("ид_объект")["событий_об"].quantile(0.75)
    q25 = clean.groupby("ид_объект")["событий_об"].quantile(0.25)
    df["z_объект"] = ((df["событий_об"] - df["ид_объект"].map(med_ev)) /
                      (df["ид_объект"].map(q75) - df["ид_объект"].map(q25) + 1e-6))

    df = df.drop(columns=["аномально", "год_неделя", "день_года", "месяц"])
    if out_csv is not None:
        out_csv = pathlib.Path(out_csv)
        df.to_csv(out_csv, index=False, encoding="utf-8-sig")
        print(f"Контекст объектов сохранён: {out_csv.name}, строк: {len(df):,}")
    return df


def make_object_panel(
    types: Optional[Iterable[str]] = None,
    years: Optional[Iterable[str]] = None,
    fault_statuses: Optional[set] = None,
    noise_values: Optional[set] = None,
    out_csv: Optional[pathlib.Path] = None,
    recompute: bool = False,
    include_all_channels: bool = True,
) -> pd.DataFrame:
    """Суточная панель «объект × дата» — контекст по ВСЕМ каналам объекта.

    Берём объекты, у которых есть хотя бы один канал из `types` (WEAR).
    Для каждого такого объекта агрегируем события/тревоги/неисправности/шум
    по **всем** каналам объекта из справочника (`include_all_channels=True`),
    отдельно по WEAR-каналам, считаем доли неисправных каналов, rolling-окна
    3/7/14/30 дней, z-скор активности объекта и сезонные признаки.
    Аномальные (кампанийные) недели нейтрализуются медианой объекта — как в
    пер-канальной панели. Сохраняется в `daily_panel_object_context.csv`.

    Возвращает DataFrame с колонками `ид_объект`, `дата` и признаками с
    суффиксом `_об` (плюс статика `n_каналов_об`, `n_пром_каналов_об`).
    """
    if types is None:
        types = WEAR_TYPES
    types = list(types)
    years = list(years) if years is not None else list(map(str, range(2019, 2027)))
    if fault_statuses is None:
        fault_statuses = FAULT_STATUSES
    if noise_values is None:
        noise_values = NOISE_VALUES
    if out_csv is None:
        out_csv = DATASET / "daily_panel_object_context.csv"
    out_csv = pathlib.Path(out_csv)
    if not recompute and out_csv.exists():
        return pd.read_csv(out_csv, dtype={"ид_объект": str, "дата": str})

    ref_ch = du.load_ref_channels()[["ид_канала_данных", "тип_датчика", "ид_объект"]]
    ref_ch = ref_ch.dropna(subset=["ид_объект"])
    wear_ch = ref_ch[ref_ch["тип_датчика"].isin(types)].copy()
    obj_set = set(wear_ch["ид_объект"])
    ch_all = ref_ch[ref_ch["ид_объект"].isin(obj_set)].copy()
    if not include_all_channels:
        ch_all = ch_all[ch_all["тип_датчика"].isin(types)]

    obj_map = dict(zip(ch_all["ид_канала_данных"], ch_all["ид_объект"]))
    ch_set = set(ch_all["ид_канала_данных"])
    prom_ch = set(wear_ch["ид_канала_данных"])

    year_parts: list[pd.DataFrame] = []
    for year in years:
        agg = _aggregate_object_year(year, ch_set, obj_map, prom_ch,
                                     fault_statuses, noise_values)
        if len(agg):
            year_parts.append(agg)
            print(f"  ext-journal-{year}: done")

    if not year_parts:
        raise ValueError(f"make_object_panel: нет данных за годы {years}")
    df = pd.concat(year_parts, ignore_index=True)
    df = finalize_object_panel(df, types=types, out_csv=out_csv)
    return df


def add_object_context(panel: pd.DataFrame,
                       obj_csv: Optional[pathlib.Path] = None,
                       recompute: bool = False) -> pd.DataFrame:
    """Дополняет панель «канал × день» контекстом объекта (все каналы).

    Для каждой строки канала добавляются признаки объекта за тот же день:
    счётчики/доли по всем каналам, rolling-окна 7/30д, z_объект — и
    композитные признаки «соседних» каналов (контекст без собственного
    вклада канала): `..._соседей_день/7д/30д`.
    """
    if obj_csv is not None:
        obj = pd.read_csv(obj_csv, dtype={"ид_объект": str, "дата": str})
    else:
        obj = make_object_panel(recompute=recompute)

    out = panel.copy()
    out["_obj_key"] = out["ид_объект"].astype("Int64")
    obj = obj.copy()
    obj["_obj_key"] = obj["ид_объект"].astype("Int64")
    obj = obj.drop(columns=["ид_объект"])
    out = out.merge(obj, on=["_obj_key", "дата"], how="left")
    out = out.drop(columns=["_obj_key"])

    # Числовые признаки объекта: отсутствие строки объекта ⇒ 0 событий за день
    fill_zero = [c for c in obj.columns
                 if c != "дата" and c in out.columns and pd.api.types.is_numeric_dtype(out[c])]
    out[fill_zero] = out[fill_zero].fillna(0)

    # Композитные признаки «соседи»: контекст объекта без собственного канала
    out["неисправн_соседей_день"] = out["неисправностей_об"] - out["неисправностей"]
    out["неисправн_соседей_7д"] = out["неисправностей_об_7д"] - out["неисправностей_7д"]
    out["неисправн_соседей_30д"] = out["неисправностей_об_30д"] - out["неисправностей_30д"]
    out["событий_соседей_7д"] = out["событий_об_7д"] - out["событий_7д"]
    out["событий_соседей_30д"] = out["событий_об_30д"] - out["событий_30д"]
    own = (out["неисправностей"] > 0).astype(int)
    out["доля_соседей_неисправны_день"] = (
        out["каналы_неисправны_об"] - own) / (out["n_каналов_об"] - 1.0).replace(0, np.nan)
    return out


# ---------------------------------------------------------------------------
# Суб-суточный панэль «канал × 6ч-бакет» и горизонты 6/12/24/48 часов
# ---------------------------------------------------------------------------
# Журнал содержит `время`, поэтому события можно агрегировать в 6-часовые
# бакеты. Цели цель_6ч/12ч/24ч/48ч = «любая неисправность канала в течение
# следующих 1/2/4/8 бакетов». Признаки — суммы за календарные окна 12ч/24ч/48ч
# /7д/30д, z-скор событий, сезонность, контекст объекта (суточной агрегации).


def _aggregate_bucket_year(year: str, ch_set, fault_statuses: set,
                           noise_values: set) -> pd.DataFrame:
    """События по ВСЕМ WEAR-каналам за год → (ид_канала_данных, бакет, счётчики).

    Бакет = 6-часовой интервал (int: число бакетов от эпохи). Возвращает
    колонки: ид_канала_данных, бакет, событий, тревог, неисправностей, шума.
    """
    cols = ["ид_канала_данных", "бакет", "событий", "тревог", "неисправностей", "шума"]
    hour_ns = BUCKET_HOURS * 3600 * 10 ** 9
    for fp in du.journal_files():
        if fp.name.split("-")[2].split(".")[0] != year:
            continue
        rows: list[pd.DataFrame] = []
        for ch in du.read_chunks(fp, cols=["ид_канала_данных", "дата", "время",
                                           "тревожное", "значение_датчика"],
                                 chunksize=500_000):
            m = ch["ид_канала_данных"].isin(ch_set)
            if not m.any():
                continue
            ch = ch[m].copy()
            ts = pd.to_datetime(ch["дата"] + " " + ch["время"].fillna("00:00:00"),
                                format="%Y-%m-%d %H:%M:%S", errors="coerce")
            ch = ch[ts.notna()]
            if not len(ch):
                continue
            # pandas 3 может вернуть datetime64[us] — приводим к ns явно
            ch["бакет"] = (ts.astype("datetime64[ns]").astype("int64") // hour_ns)
            ch["_неиспр"] = ch["значение_датчика"].isin(fault_statuses)
            ch["_шум"] = ch["значение_датчика"].isin(noise_values)
            ch["_трев"] = ch["тревожное"].eq("t")
            chd = ch.groupby(["ид_канала_данных", "бакет"], sort=False).agg(
                событий=("ид_канала_данных", "size"),
                тревог=("_трев", "sum"),
                неисправностей=("_неиспр", "sum"),
                шума=("_шум", "sum"),
            ).reset_index()
            rows.append(chd)
        if not rows:
            return pd.DataFrame(columns=cols)
        chd = pd.concat(rows, ignore_index=True)
        # дедупликация границ чанков: (канал, бакет) суммируется
        chd = chd.groupby(["ид_канала_данных", "бакет"], sort=False) \
                 .agg(событий=("событий", "sum"), тревог=("тревог", "sum"),
                      неисправностей=("неисправностей", "sum"),
                      шума=("шума", "sum")).reset_index()
        return chd
    return pd.DataFrame(columns=cols)


def _add_bucket_windows(df: pd.DataFrame, count_cols, windows=BUCKET_WINDOWS,
                        group_col: str = "ид_канала_данных") -> pd.DataFrame:
    """Календарные окна по 6-часовым бакетам (суммы за 12ч/24ч/48ч/7д/30д).

    Панэль спарс (строки только бакеты с событиями), поэтому окна считаются
    точно в календарных бакетах: префиксные суммы по группе + searchsorted по
    границе окна. Добавляет колонки `{col}_сум_{12ч|24ч|48ч|7д|30д}`.
    `group_col` — ключ группировки (канал или объект).
    """
    df = df.sort_values([group_col, "бакет"]).reset_index(drop=True)
    for col in count_cols:
        df[f"_pref_{col}"] = df.groupby(group_col, sort=False)[col].cumsum()
    bucket = df["бакет"].to_numpy(dtype=np.int64)
    groups = df.groupby(group_col, sort=False).indices
    for W in windows:
        label = f"{W * BUCKET_HOURS}ч" if W * BUCKET_HOURS < 168 else f"{W * BUCKET_HOURS // 24}д"
        for col in count_cols:
            out = np.zeros(len(df), dtype=np.float64)
            pref = df[f"_pref_{col}"].to_numpy(dtype=np.float64)
            for sl in groups.values():
                sl = np.asarray(sl)
                b = bucket[sl]
                lo = np.searchsorted(b, b - W + 1, side="left")
                res = pref[sl].copy()
                m = lo > 0
                res[m] -= pref[sl[np.maximum(lo[m] - 1, 0)]]
                out[sl] = res
            df[f"{col}_сум_{label}"] = out
    df = df.drop(columns=[f"_pref_{col}" for col in count_cols])
    return df


def _add_horizon_targets(df: pd.DataFrame) -> pd.DataFrame:
    """Цели цель_6ч/12ч/24ч/48ч: неисправность канала в ближайшие N бакетов.

    Для каждой строки (канал, бакет) ищется ближайший СТРОГО будущий бакет с
    неисправностью (searchsorted по бакетам канала). В кампанийных неделях
    цели = NaN (как в суточном панэле).
    """
    bucket = df["бакет"].to_numpy(dtype=np.int64)
    nf_vals = df["неисправностей"].to_numpy(dtype=np.float64)
    next_fault = np.full(len(df), np.inf)
    groups = df.groupby("ид_канала_данных", sort=False).indices
    for sl in groups.values():
        sl = np.asarray(sl)
        b = bucket[sl]
        fb = b[nf_vals[sl] > 0]
        if not len(fb):
            continue
        idx = np.searchsorted(fb, b, side="right")
        nf = np.where(idx < len(fb), fb[np.minimum(idx, len(fb) - 1)], np.inf)
        next_fault[sl] = nf
    dist = next_fault - bucket
    for name, k in HORIZONS.items():
        df[f"цель_{name}"] = (dist <= k).astype(int)
    df.loc[df["аномально"], [f"цель_{n}" for n in HORIZONS]] = np.nan
    return df


def add_series_targets(panel: pd.DataFrame, gap_buckets: int = SERIES_GAP) -> pd.DataFrame:
    """«Серийная» разметка: событие = ПЕРВАЯ неисправность серии.

    Серия: неисправные бакеты канала, идущие с разрывом < gap_buckets (по
    умолчанию 4 бакета = 24 ч). Последующие неисправности той же серии —
    продолжение, для прогноза события неактуальны.

    Добавляет колонки:
    - серия_старт: 1, если этот бакет — первая неисправность серии;
    - дни_до_серии: до СЛЕДУЮЩЕГО старта серии в сутках (NaN — цензурировано);
    - цель_серии_{6ч|12ч|24ч|48ч}: новый инцидент (старт серии) в ближайшие
      N бакетов (NaN в кампанийных неделях).
    """
    out = panel.copy()
    out = out.sort_values(["ид_канала_данных", "бакет"]).reset_index(drop=True)
    bucket = out["бакет"].to_numpy(dtype=np.int64)
    nf = out["неисправностей"].to_numpy(dtype=np.float64)
    is_fault = nf > 0
    NEG = -2 ** 62

    # последний неисправный бакет СТРОГО раньше текущего (по каналу)
    prev = np.full(len(out), NEG, dtype=np.int64)
    groups = out.groupby("ид_канала_данных", sort=False).indices
    for sl in groups.values():
        sl = np.asarray(sl)
        b = bucket[sl]
        fb = b[is_fault[sl]]
        if not len(fb):
            continue
        i = np.searchsorted(fb, b, side="left") - 1
        pb = np.where(i >= 0, fb[np.maximum(i, 0)], NEG)
        same = (i >= 0) & (fb[np.maximum(i, 0)] == b)
        i2 = np.where(same, i - 1, i)
        pb2 = np.where(i2 >= 0, fb[np.maximum(i2, 0)], NEG)
        prev[sl] = pb2

    out["серия_старт"] = (is_fault & ((bucket - prev) > gap_buckets)).astype(int)

    # следующий старт серии строго в будущем
    next_start = np.full(len(out), np.inf)
    for sl in groups.values():
        sl = np.asarray(sl)
        sb = bucket[sl][out["серия_старт"].to_numpy()[sl] == 1]
        if not len(sb):
            continue
        j = np.searchsorted(sb, bucket[sl], side="right")
        ns = np.where(j < len(sb), sb[np.minimum(j, len(sb) - 1)], np.inf)
        next_start[sl] = ns

    dist = next_start - bucket
    out["дни_до_серии"] = np.where(np.isfinite(dist), dist / (24 / BUCKET_HOURS), np.nan)
    for name, k in HORIZONS.items():
        out[f"цель_серии_{name}"] = (dist <= k).astype(int)
    out.loc[out["аномально"], [f"цель_серии_{n}" for n in HORIZONS]] = np.nan
    return out


def merge_object_context(panel: pd.DataFrame,
                         obj_csv: Optional[pathlib.Path] = None,
                         recompute: bool = False) -> pd.DataFrame:
    """Мержит суточный контекст объекта (все каналы) в произвольную панель.

    Ключ: (ид_объект, дата). Отсутствие строки объекта за день ⇒ 0 событий.
    """
    if obj_csv is not None:
        obj = pd.read_csv(obj_csv, dtype={"ид_объект": str, "дата": str})
    else:
        obj = make_object_panel(recompute=recompute)
    out = panel.copy()
    out["ид_объект"] = out["ид_объект"].astype(str)
    out["дата"] = out["дата"].astype(str)
    obj = obj.copy()
    obj["ид_объект"] = obj["ид_объект"].astype(str)
    obj["дата"] = obj["дата"].astype(str)
    out = out.merge(obj, on=["ид_объект", "дата"], how="left")
    num = [c for c in obj.columns if c not in ("ид_объект", "дата")
           and pd.api.types.is_numeric_dtype(out[c])]
    out[num] = out[num].fillna(0)
    return out


def make_subdaily_panel(
    types: Optional[Iterable[str]] = None,
    years: Optional[Iterable[str]] = None,
    recompute: bool = False,
    out_csv: Optional[pathlib.Path] = None,
) -> pd.DataFrame:
    """6-часовой панэль «канал × бакет» для горизонтов 6/12/24/48 часов.

    Источник: сырые агрегаты `dataset/_buckets_raw/_buckets_raw_<год>.csv`
    (сборка: `notebooks/00_data_pipeline.ipynb`). Добавляет:
    - счётчики за бакет: событий, тревог, неисправностей, шума;
    - календарные окна 12ч/24ч/48ч/7д/30д (`_сум_...`);
    - z_событий (пер-канальная нормализация, чистые бакеты);
    - сезонность: час_бакета, день_недели, месяц, день_года, год_неделя;
    - цели цель_6ч/12ч/24ч/48ч (NaN в кампанийных неделях);
    - бакетный контекст объекта (все каналы объекта за тот же 6ч бакет
      и его календарные окна — без утечки будущего в пределах дня).
    """
    if types is None:
        types = WEAR_TYPES
    types = list(types)
    years = list(years) if years is not None else list(map(str, range(2019, 2027)))
    if out_csv is None:
        out_csv = DATASET / "subdaily_panel_wear_6h.csv"
    out_csv = pathlib.Path(out_csv)
    if not recompute and out_csv.exists():
        return pd.read_csv(out_csv, dtype={"ид_канала_данных": str, "дата": str})

    ref_ch = du.load_ref_channels()[["ид_канала_данных", "тип_датчика", "ид_объект"]]
    ref_ch = ref_ch.dropna(subset=["ид_объект"])
    ch_set = set(ref_ch.loc[ref_ch["тип_датчика"].isin(types), "ид_канала_данных"])

    if recompute:
        parts: list[pd.DataFrame] = []
        for year in years:
            agg = _aggregate_bucket_year(year, ch_set, FAULT_STATUSES, NOISE_VALUES)
            if len(agg):
                parts.append(agg)
                print(f"  {year}: {len(agg):,} бакето-строк")
        if not parts:
            raise ValueError(f"make_subdaily_panel: нет данных за {years}")
        df = pd.concat(parts, ignore_index=True)
    else:
        if not _BUCKET_RAW_DIR.exists():
            raise FileNotFoundError(
                "Нет сырых бакетов: сначала шаг 2 в notebooks/00_data_pipeline.ipynb")
        files = sorted(_BUCKET_RAW_DIR.glob("_buckets_raw_*.csv"))
        parts = [pd.read_csv(f, dtype={"ид_канала_данных": str}) for f in files]
        if not parts:
            raise ValueError(_BUCKET_RAW_DIR)
        df = pd.concat(parts, ignore_index=True)

    df = df.merge(ref_ch, on="ид_канала_данных", how="left").dropna(subset=["ид_объект"])
    df["тип_датчика"] = df["тип_датчика"].fillna("прочее")
    df["ид_объект"] = df["ид_объект"].astype(str)
    df["ид_канала_данных"] = df["ид_канала_данных"].astype(str)

    hour_ns = BUCKET_HOURS * 3600 * 10 ** 9
    ts = (df["бакет"].to_numpy(dtype=np.int64) * hour_ns).astype("datetime64[ns]")
    dts = pd.Series(ts)
    df["дата"] = dts.dt.strftime("%Y-%m-%d")
    df["час_бакета"] = dts.dt.hour
    df["день_недели"] = dts.dt.dayofweek
    df["месяц"] = dts.dt.month
    df["день_года"] = dts.dt.dayofyear
    iso = dts.dt.isocalendar()
    df["год_неделя"] = iso["year"].astype(int) * 100 + iso["week"].astype(int)
    df["аномально"] = df["год_неделя"].map(du.week_is_campaign)

    count_cols = ["событий", "тревог", "неисправностей", "шума"]
    df = _add_bucket_windows(df, count_cols, windows=BUCKET_WINDOWS)

    clean = df[~df["аномально"]]
    med = clean.groupby("ид_канала_данных")["событий"].median()
    iqr = (clean.groupby("ид_канала_данных")["событий"].quantile(0.75)
           - clean.groupby("ид_канала_данных")["событий"].quantile(0.25))
    df["z_событий"] = ((df["событий"] - df["ид_канала_данных"].map(med)) /
                       (df["ид_канала_данных"].map(iqr) + 1e-6))

    df = _add_horizon_targets(df)

    # Бакетный контекст объекта: агрегация ВСЕХ каналов объекта за ТОТ ЖЕ
    # 6-часовой бакет и его календарные окна. Без утечки: учитывается только
    # прошлое и текущий интервал, а не будущее в пределах дня.
    count_cols_ob = ["событий_об_б", "тревог_об_б", "неисправностей_об_б",
                     "шума_об_б", "каналов_активных_об_б"]
    obj_blk = df.groupby(["ид_объект", "бакет"], sort=False).agg(
        событий_об_б=("событий", "sum"),
        тревог_об_б=("тревог", "sum"),
        неисправностей_об_б=("неисправностей", "sum"),
        шума_об_б=("шума", "sum"),
        каналов_активных_об_б=("ид_канала_данных", "nunique"),
    ).reset_index()
    obj_blk = _add_bucket_windows(obj_blk, count_cols_ob, windows=BUCKET_WINDOWS,
                                  group_col="ид_объект")
    df = df.merge(obj_blk, on=["ид_объект", "бакет"], how="left")
    ob_num = [c for c in obj_blk.columns if c not in ("ид_объект", "бакет")]
    df[ob_num] = df[ob_num].fillna(0)

    df = df.sort_values(["ид_канала_данных", "бакет"]).reset_index(drop=True)
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"Суб-суточный панэль сохранён: {out_csv.name}, строк: {len(df):,}")
    return df


def split_by_time(df: pd.DataFrame, train_end: str = "2024-12-31",
                  val_end: str = "2025-12-31") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Временной сплит по дате (аномальные недели исключены из обучения)."""
    clean = df[~df["аномально"]].copy()
    dt = pd.to_datetime(clean["дата"])
    train = clean[dt <= train_end]
    val = clean[(dt > train_end) & (dt <= val_end)]
    test = clean[dt > val_end]
    return train, val, test
    types = list(types)
    years = list(years) if years is not None else list(map(str, range(2019, 2027)))
    key = "_".join(t.replace(" ", "_") for t in types)
    if out_csv is None:
        out_csv = DATASET / f"daily_panel_{key}.csv"
    if not recompute and out_csv.exists():
        return pd.read_csv(out_csv, dtype={"ид_канала_данных": str, "дата": str})

    ref_ch = du.load_ref_channels()[["ид_канала_данных", "тип_датчика", "ид_объект"]]
    ch_set = set(ref_ch.loc[ref_ch["тип_датчика"].isin(types), "ид_канала_данных"])
    obj_map = dict(zip(ref_ch["ид_канала_данных"], ref_ch["ид_объект"]))