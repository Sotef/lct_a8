# -*- coding: utf-8 -*-
"""Живая подача журнала (SIM_FEED=1) — «как в реальной работе».

Реплей по предзагруженной панели (panel_max читается из panels/*.csv) заменяется схемой:

    грязный ext-journal-*.csv ──(ленивое чтение порциями)──►
        только «наступившие» 6ч-бакеты ──► агрегаты: data/stream/raw/buckets_*.parquet
        ──► пересборка признаков/панели из накопленного кэша ──► CatBoost.predict_proba

Файл читается **один раз последовательно** (`pd.read_csv(chunksize=...)`), «будущие»
строки складываются в буфер и отдаются на следующем тике — данные приходят ровно так,
как приходил бы поток, а пейсинг задаёт сим-клок.
"""
from __future__ import annotations

import logging
import time

import pandas as pd

from .. import config
from .. import task_cfg
from ..adapters.journal import JOURNAL_COLS, JournalStreamAdapter, bucket_from_timestamp
from ..research_bridge import module as _m

log = logging.getLogger("stream")


class JournalFeed:
    """Потоковая подача из журнала СМВУ с пейсингом по сим-времени."""

    def __init__(self, year: str | None = None, source=None, chunksize: int | None = None,
                 max_chunks_per_tick: int = 400):
        du = _m("data_utils")
        ref = du.load_ref_channels()
        channels: set = set()
        for cfg in task_cfg.TASKS.values():
            channels |= set(ref.loc[ref["тип_датчика"].isin(cfg["types"]), "ид_канала_данных"])
        self.adapter = JournalStreamAdapter(year=(year or config.SIM_YEAR), source=source,
                                            channels=channels,
                                            extra_cols=task_cfg.extra_specs(ref),
                                            cache_dir=config.RAW_DIR)
        self.chunksize = int(chunksize or config.SIM_FEED_CHUNK)
        self.max_chunks_per_tick = int(max_chunks_per_tick)
        self._reader = None
        self._future = pd.DataFrame()          # прочитано, но ещё «не наступило»
        self.stats = {"ticks": 0, "rows_read": 0, "rows_due": 0, "cache_rows": 0,
                      "last_sec": None, "max_ts": None, "eof": False}

    # --- чтение файла ---------------------------------------------------------
    def _iterator(self):
        if self._reader is None:
            src = self.adapter.source
            if not src.exists():
                raise FileNotFoundError(
                    f"нет журнала для живой подачи: {src}. "
                    f"SIM_FEED=1 требует исходные ext-journal-*.csv (STREAM_SOURCE).")
            log.info("stream: открываю журнал %s порциями по %s строк", src, self.chunksize)
            self._reader = pd.read_csv(src, sep=",", dtype=str, low_memory=False,
                                       usecols=JOURNAL_COLS, chunksize=self.chunksize,
                                       on_bad_lines="skip", encoding="utf-8-sig")
        return self._reader

    def next_chunk(self) -> pd.DataFrame | None:
        try:
            return next(self._iterator())
        except StopIteration:
            self.stats["eof"] = True
            return None

    def _with_bucket(self, chunk: pd.DataFrame) -> pd.DataFrame:
        """Служебные/битые строки отбрасываем, добавляем 6ч-бакет."""
        chunk = chunk[chunk["ид_события"].ne("ид_события")]
        if not len(chunk):
            return chunk
        ts = self.adapter._parse_ts(chunk)
        good = ts.notna().to_numpy()
        chunk = chunk[good].copy()
        if not len(chunk):
            return chunk
        chunk["бакет"] = bucket_from_timestamp(pd.Series(ts.to_numpy()[good])).to_numpy()
        return chunk

    # --- основной вызов -------------------------------------------------------
    def ingest_until(self, bucket: int) -> dict:
        """Дочитать журнал до конца бакета `bucket` включительно и обновить кэш."""
        t0 = time.time()
        due_parts: list[pd.DataFrame] = []
        rows_read = 0
        chunks = 0
        buf = self._future
        self._future = pd.DataFrame()
        while True:
            if not len(buf):
                chunk = self.next_chunk()
                if chunk is None:
                    break
                chunks += 1
                rows_read += len(chunk)
                buf = self._with_bucket(chunk)
                if not len(buf):
                    if chunks >= self.max_chunks_per_tick:
                        break
                    continue
            late = (buf["бакет"] > bucket).to_numpy()
            if late.any():
                due_parts.append(buf[~late])
                self._future = buf[late]
                break
            due_parts.append(buf)
            buf = pd.DataFrame()
            if chunks >= self.max_chunks_per_tick:
                log.warning("stream: достигнут лимит чанков за тик (%s) — остаток следующим тиком",
                            self.max_chunks_per_tick)
                break

        due = pd.concat(due_parts, ignore_index=True) if due_parts else pd.DataFrame()
        res = self.adapter.append_events(due)
        self.stats.update({
            "ticks": self.stats["ticks"] + 1,
            "rows_read": self.stats["rows_read"] + rows_read,
            "rows_due": int(len(due)),
            "cache_rows": res.get("cache_rows"),
            "max_ts": res.get("max_ts"),
            "last_sec": round(time.time() - t0, 2),
        })
        log.info("stream feed: бакет %s (%s) — прочитано %s строк, принято %s, "
                 "кэш %s строк, max_ts %s, %.2f с",
                 bucket, ts_of_bucket(bucket), rows_read, len(due),
                 res.get("cache_rows"), res.get("max_ts"), self.stats["last_sec"])
        return dict(self.stats)

    def journal_end_bucket(self) -> int:
        return journal_end_bucket()


def ts_of_bucket(bucket: int) -> str:
    from .ingestion import _bucket_ts
    return _bucket_ts(int(bucket)).strftime("%Y-%m-%d %H:%M")


def _bucket_of_ts(stamp) -> int:
    return int(bucket_from_timestamp(pd.Series([pd.Timestamp(stamp).to_datetime64()]))[0])


def journal_end_bucket(default: str = "2026-06-30T18:00:00") -> int:
    """Граница подачи: SIM_FEED_END, иначе — timestamp последней строки журнала."""
    if config.SIM_FEED_END:
        return _bucket_of_ts(config.SIM_FEED_END)
    src = config.STREAM_SOURCE
    try:
        with open(src, "rb") as f:                       # хвост файла: последняя полная строка
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 65536))
            tail = f.read().decode("utf-8-sig", errors="ignore").strip().splitlines()
        parts = tail[-1].split(",")
        return _bucket_of_ts(f"{parts[2]} {parts[3]}")
    except Exception as exc:  # noqa: BLE001
        log.warning("stream: не удалось прочитать конец журнала (%s) — использую %s",
                    exc, default)
        return _bucket_of_ts(default)
