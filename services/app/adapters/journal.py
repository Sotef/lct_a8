# -*- coding: utf-8 -*-
"""Адаптер журнала СМВУ (read-only, потоковая подача).

Читает `ext-journal-<год>.csv` ЧАНКАМИ (стриминг), агрегирует в 6-часовые бакеты
(ид_канала_данных, бакет, событий, тревог, неисправностей, шума + все extra_cols
всех задач) и инкрементально дозаписывает в кэш `services/data/raw/buckets_<год>.parquet`.

Инкрементальность: checkpoint = максимум обработанного `ид_события`. Повторные
проходы (переигрывание файла) НЕ удваивают счётчики, т.к. фильтр строго > max_id.

Формат бакета совпадает с research/features.BUCKET_HOURS (6 ч): целое число
6-часовых интервалов от эпохи. Агрегация = та же, что `features._aggregate_bucket_year`
(проверяется сквозным тестом по 2026).
"""
from __future__ import annotations

import json
import pathlib
import time

import numpy as np
import pandas as pd

from .. import config
from ..research_bridge import module as _m

HOUR_NS = 6 * 3600 * 10 ** 9                 # 6ч в наносекундах
JOURNAL_COLS = ["ид_события", "ид_канала_данных", "дата", "время", "тревожное",
                "значение_датчика"]


def bucket_from_timestamp(ts) -> np.ndarray:
    """6-часовой бакет из datetime-серии."""
    return (ts.astype("datetime64[ns]").astype("int64") // HOUR_NS)


def bucket_to_timestamp(b) -> pd.Timestamp:
    return (np.int64(b) * HOUR_NS).astype("datetime64[ns]")


class JournalStreamAdapter:
    """Потоковый read-only адаптер журнала СМВУ."""

    name = "smvu_journal"
    primary_key = "ид_события"
    columns = JOURNAL_COLS

    def __init__(self, source: pathlib.Path | None = None,
                 year: str = "2026",
                 channels: set | None = None,
                 extra_cols: dict | None = None,
                 cache_dir: pathlib.Path | None = None):
        self.source = pathlib.Path(source or config.STREAM_SOURCE)
        self.year = year
        self.channels = set(channels or ())
        self.extra_cols = extra_cols or {}
        self.cache_dir = pathlib.Path(cache_dir or config.RAW_DIR)
        self.cache_path = self.cache_dir / f"buckets_{year}.parquet"
        self.ckpt_path = self.cache_dir / f"checkpoint_{year}.json"

    # -- контрольная точка -----------------------------------------------------
    @property
    def checkpoint_id(self):
        if not self.ckpt_path.exists():
            return None
        data = json.loads(self.ckpt_path.read_text(encoding="utf-8"))
        v = data.get("max_ид_события")
        return int(v) if v is not None else None

    def _save_checkpoint(self, max_id) -> None:
        payload = {"year": self.year, "max_ид_события": max_id,
                   "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.ckpt_path.write_text(json.dumps(payload, ensure_ascii=False),
                                  encoding="utf-8")

    # -- базовые счётчики -------------------------------------------------------
    @property
    def _fault_statuses(self):
        return frozenset(_m("features").FAULT_STATUSES)

    @property
    def _noise_values(self):
        return frozenset(_m("features").NOISE_VALUES)

    def _base_agg(self, chunk: pd.DataFrame) -> pd.DataFrame:
        """Агрегация одного чанка в (ид_канала_данных, бакет, счётчики)."""
        ts = pd.to_datetime(chunk["дата"] + " " + chunk["время"].fillna("00:00:00"),
                            format="%Y-%m-%d %H:%M:%S", errors="coerce")
        chunk = chunk[ts.notna()]
        if not len(chunk):
            return pd.DataFrame()
        good = ts.notna().to_numpy()
        # ВАЖНО: позиционное присваивание через to_numpy() — индекс чанка после
        # логической маски может быть не-contiguous, и Series-выравнивание
        # зануляло бы весь бакет (pandas 3: datetime64[us]).
        chunk["бакет"] = bucket_from_timestamp(pd.Series(ts[good].to_numpy())).to_numpy()
        chunk["_неиспр"] = chunk["значение_датчика"].isin(self._fault_statuses).to_numpy()
        chunk["_шум"] = chunk["значение_датчика"].isin(self._noise_values).to_numpy()
        chunk["_трев"] = chunk["тревожное"].eq("t").to_numpy()

        ch_ids = chunk["ид_канала_данных"].astype(str)
        values = chunk["значение_датчика"].fillna("<нет>").astype(str)
        agg: dict = {
            "событий": ("ид_канала_данных", "size"),
            "тревог": ("_трев", "sum"),
            "неисправностей": ("_неиспр", "sum"),
            "шума": ("_шум", "sum"),
        }
        mask_cache: dict = {}
        for name, spec in self.extra_cols.items():
            if spec.get("kind") == "alarm_by_type":
                chans = set(spec.get("channels", ())) or set(spec.get("types", ()))
                key = ("alarm", frozenset(chans))
                mask = mask_cache.get(key)
                if mask is None:
                    mask = ch_ids.isin(chans).to_numpy() & chunk["_трев"].to_numpy()
                    mask_cache[key] = mask
            elif spec.get("kind") == "value_by_type":
                chans = set(spec.get("channels", ()))
                vals = set(spec.get("values", ()))
                key = ("value", frozenset(chans), frozenset(vals))
                mask = mask_cache.get(key)
                if mask is None:
                    mask = (ch_ids.isin(chans).to_numpy()
                            & values.isin(vals).to_numpy())
                    mask_cache[key] = mask
            else:
                continue
            chunk[f"_x_{name}"] = mask
            agg[name] = (f"_x_{name}", "sum")

        return (chunk.groupby(["ид_канала_данных", "бакет"], sort=False)
                     .agg(**agg).reset_index())

    # -- потоковый инкрементальный ингвест --------------------------------------
    def _parse_ts(self, chunk: pd.DataFrame):
        return pd.to_datetime(chunk["дата"] + " " + chunk["время"].fillna("00:00:00"),
                              format="%Y-%m-%d %H:%M:%S", errors="coerce")

    @property
    def checkpoint_ts(self):
        if not self.ckpt_path.exists():
            return None
        data = json.loads(self.ckpt_path.read_text(encoding="utf-8"))
        v = data.get("max_ts")
        return pd.Timestamp(v) if v else None

    def _save_checkpoint_ts(self, max_ts) -> None:
        payload = {"year": self.year,
                   "max_ts": str(max_ts),
                   "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.ckpt_path.write_text(json.dumps(payload, ensure_ascii=False),
                                  encoding="utf-8")

    def ingest(self, limit_rows: int | None = None,
               chunksize: int = 1_000_000) -> dict:
        """Стримирует исходный CSV и формирует кэш 6ч-бакетов.

        Журнал хронологичен, поэтому checkpoint = максимальный timestamp
        обработанной строки (id события НЕ монотонен — им нельзя дедуплицировать!).
        - первый проход: кэш ЗАМЕНЯЕТСЯ полным агрегатом (идемпотентно);
        - повторный проход: добавляются только строки позже max_ts (append).
        Возвращает {rows_read, rows_new, buckets_total, max_ts}.
        """
        if not self.source.exists():
            raise FileNotFoundError(self.source)
        max_ts_prev = self.checkpoint_ts
        full = max_ts_prev is None
        chans = self.channels

        row_chunks, new_rows = 0, 0
        cumul_parts: list[pd.DataFrame] = []
        reader = pd.read_csv(self.source, sep=",", dtype=str, low_memory=False,
                             usecols=JOURNAL_COLS, chunksize=chunksize,
                             on_bad_lines="skip", encoding="utf-8-sig")
        last_ts = max_ts_prev
        for chunk in reader:
            chunk = chunk[chunk["ид_события"].ne("ид_события")]
            if not len(chunk):
                continue
            row_chunks += len(chunk)
            ts = self._parse_ts(chunk)
            chunk = chunk[ts.notna()]
            if not len(chunk):
                if limit_rows and row_chunks >= limit_rows:
                    break
                continue
            ts = ts[ts.notna()]
            if not full:
                newer = (ts > max_ts_prev).to_numpy()
                chunk = chunk[newer]
                if not len(chunk):
                    if limit_rows and row_chunks >= limit_rows:
                        break
                    continue
                ts = ts[newer]
            tmax = ts.max()
            if last_ts is None or tmax > last_ts:
                last_ts = tmax
            if chans:
                chunk = chunk[chunk["ид_канала_данных"].astype(str).isin(chans)]
            if not len(chunk):
                if limit_rows and row_chunks >= limit_rows:
                    break
                continue
            new_rows += len(chunk)
            agg = self._base_agg(chunk)
            if len(agg):
                agg["ид_канала_данных"] = agg["ид_канала_данных"].astype(str)
                for col in agg.columns:
                    if col != "ид_канала_данных":
                        agg[col] = agg[col].astype("int64")
                cumul_parts.append(agg.copy())
            if limit_rows and row_chunks >= limit_rows:
                break

        old = pd.DataFrame() if full else self._read_cache()
        parts = ([old] if len(old) else []) + cumul_parts
        if parts:
            df = pd.concat(parts, ignore_index=True)
            sum_cols = {c: (c, "sum") for c in df.columns
                        if c not in ("ид_канала_данных", "бакет")}
            df = (df.groupby(["ид_канала_данных", "бакет"], sort=False)
                    .agg(**sum_cols).reset_index()
                    .sort_values(["ид_канала_данных", "бакет"])
                    .reset_index(drop=True))
            num_cols = [c for c in df.columns if c != "ид_канала_данных"]
            df[num_cols] = df[num_cols].astype("int64")
            df["ид_канала_данных"] = df["ид_канала_данных"].astype(str)
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(self.cache_path, index=False)
        else:
            df = old
        if new_rows or (full and len(cumul_parts)):
            self._save_checkpoint_ts(last_ts)
        return {"rows_read": row_chunks, "rows_new": new_rows,
                "buckets_total": int(len(df)) if len(df) else 0,
                "max_ts": str(last_ts) if last_ts is not None else None}

    def _read_cache(self) -> pd.DataFrame:
        if not self.cache_path.exists():
            return pd.DataFrame()
        return pd.read_parquet(self.cache_path).reset_index(drop=True)

    def _merge_aggs(self, cumul_parts: list[pd.DataFrame]) -> pd.DataFrame:
        """Слить новые агрегаты с кэшем (sum по каналу × бакету) и сохранить parquet."""
        old = self._read_cache()
        parts = ([old] if len(old) else []) + [p for p in cumul_parts if len(p)]
        if not parts:
            return old
        df = pd.concat(parts, ignore_index=True)
        sum_cols = {c: (c, "sum") for c in df.columns
                    if c not in ("ид_канала_данных", "бакет")}
        df = (df.groupby(["ид_канала_данных", "бакет"], sort=False).agg(**sum_cols)
                .reset_index().sort_values(["ид_канала_данных", "бакет"])
                .reset_index(drop=True))
        num_cols = [c for c in df.columns if c != "ид_канала_данных"]
        df[num_cols] = df[num_cols].astype("int64")
        df["ид_канала_данных"] = df["ид_канала_данных"].astype(str)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(self.cache_path, index=False)
        return df

    def append_events(self, raw: pd.DataFrame) -> dict:
        """Живая подача (SIM_FEED): агрегировать «сырые» строки и дописать в кэш.

        В отличие от `ingest()`, не читает файл, а принимает уже прочитанную порцию
        (например, 6ч-хвост журнала, который «наступил» по сим-часам).
        """
        empty = {"rows_new": 0, "cache_rows": int(len(self._read_cache())),
                 "max_ts": str(self.checkpoint_ts) if self.checkpoint_ts is not None else None}
        if raw is None or not len(raw):
            return empty
        df = raw.copy()
        if self.channels:
            df = df[df["ид_канала_данных"].astype(str).isin(self.channels)]
        if not len(df):
            return empty
        ts = self._parse_ts(df)
        keep = ts.notna()
        df, ts = df[keep], ts[keep]
        if not len(df):
            return empty
        agg = self._base_agg(df)
        if len(agg):
            agg["ид_канала_данных"] = agg["ид_канала_данных"].astype(str)
            for col in agg.columns:
                if col != "ид_канала_данных":
                    agg[col] = agg[col].astype("int64")
        merged = self._merge_aggs([agg])
        max_ts = ts.max()
        prev = self.checkpoint_ts
        if prev is None or max_ts > prev:
            self._save_checkpoint_ts(max_ts)
        return {"rows_new": int(len(df)), "cache_rows": int(len(merged)),
                "max_ts": str(max_ts)}

    def load_cache(self) -> pd.DataFrame:
        return self._read_cache()