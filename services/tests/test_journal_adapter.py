# -*- coding: utf-8 -*-
"""Юнит-тесты потокового адаптера журнала (синтетические данные, без больших файлов)."""
from __future__ import annotations

import pandas as pd
import pytest

from app.adapters.journal import JournalStreamAdapter, bucket_from_timestamp

HEADER = "ид_события,ид_канала_данных,дата,время,тревожное,значение_датчика"


def _make_journal(tmp_path, n_per_day=50, days=(1, 2, 3)):
    """Ложный журнал: каналы 100001..100003, даты из days, значения/тревоги перемешаны."""
    rows = []
    for day in days:
        for k in range(n_per_day):
            ch = 100001 + (k % 3)
            rows.append((f"{day*10**8+k}", ch, f"2026-01-{day:02d}",
                         f"{k % 24:02d}:{k % 60:02d}:{k % 60:02d}",
                         "t" if k % 5 == 0 else "f",
                         "Неисправен" if k % 7 == 0 else "0.01"))
    fp = tmp_path / "journal.csv"
    fp.write_text(HEADER + "\n" + "\n".join(
        ",".join(map(str, r)) for r in rows), encoding="utf-8")
    return fp


def test_bucket_math():
    ts = pd.Series(pd.to_datetime(["2026-01-01 00:00:00", "2026-01-01 05:59:59",
                                   "2026-01-01 06:00:00"]))
    b = bucket_from_timestamp(ts)
    assert b.tolist()[0] == b.tolist()[1]
    assert b.tolist()[2] == b.tolist()[0] + 1


def test_full_ingest_and_increment(tmp_path):
    fp = _make_journal(tmp_path)
    extra = {"неисправн_дым": {"kind": "value_by_type", "count_channels": True,
                               "channels": {"100001", "100002", "100003"},
                               "values": {"Неисправен"}}}
    a = JournalStreamAdapter(source=fp, year="2026",
                             channels={"100001", "100002", "100003"},
                             extra_cols=extra, cache_dir=tmp_path)
    st = a.ingest()
    assert st["rows_new"] > 0
    df = a.load_cache()
    bmin, bmax = int(df["бакет"].min()), int(df["бакет"].max())
    assert (bmax - bmin) == 11        # 3 суток = 12 бакетов
    total_events = int(df["событий"].sum())
    assert total_events == st["rows_new"]

    st2 = a.ingest()                  # без новых данных
    df2 = a.load_cache()
    assert st2["rows_new"] == 0
    assert int(df2["событий"].sum()) == total_events


def test_increment_appends_new_rows(tmp_path):
    fp = _make_journal(tmp_path, days=(1, 2))
    a = JournalStreamAdapter(source=fp, year="2026",
                             channels={"100001", "100002", "100003"},
                             extra_cols={}, cache_dir=tmp_path)
    st1 = a.ingest()
    assert st1["rows_new"] == 2 * 50

    # журнал растёт: дописываем в конец строки дня 3
    rows = []
    for k in range(50):
        ch = 100001 + (k % 3)
        rows.append((f"300000000{k}", ch, "2026-01-03",
                     f"{k % 24:02d}:{k % 60:02d}:{k % 60:02d}",
                     "t" if k % 5 == 0 else "f",
                     "Неисправен" if k % 7 == 0 else "0.01"))
    with open(fp, "a", encoding="utf-8") as f:
        f.write("\n" + "\n".join(",".join(map(str, r)) for r in rows))

    st2 = a.ingest()
    df2 = a.load_cache()
    assert st2["rows_new"] == 50
    assert (int(df2["бакет"].max()) - int(df2["бакет"].min())) == 11
    assert int(df2["событий"].sum()) == 3 * 50


def test_channel_filter(tmp_path):
    fp = _make_journal(tmp_path)
    a = JournalStreamAdapter(source=fp, year="2026",
                             channels={"100001"}, extra_cols={},
                             cache_dir=tmp_path)
    st = a.ingest()
    df = a.load_cache()
    assert set(df["ид_канала_данных"].unique()) <= {"100001"}
    assert st["rows_new"] >= 20


def test_first_pass_replaces_cache(tmp_path):
    """После удаления checkpoint повторный полный проход не удваивает счётчики."""
    fp = _make_journal(tmp_path)
    a = JournalStreamAdapter(source=fp, year="2026",
                             channels={"100001", "100002", "100003"},
                             extra_cols={}, cache_dir=tmp_path)
    a.ingest()
    total1 = int(a.load_cache()["событий"].sum())
    (tmp_path / "checkpoint_2026.json").unlink()   # checkpoint потерян
    a.ingest()
    assert int(a.load_cache()["событий"].sum()) == total1