# -*- coding: utf-8 -*-
"""Метаданные каналов для плана ТО: возраст оборудования.

Возраст = «сейчас» − **первая запись с этого датчика за всё доступное время**
(2019…2026). Источник — артефакт `data/channel_first_seen.csv`, собирается
скриптом `scripts/build_channel_meta.py` из помесячных бакетов research по всем
годам. Реестр оборудования (даты ввода в эксплуатацию, история ремонтов) не
используется — заказчик его не даёт, поэтому возраст — по журналу, это худший,
но доступный прокси «давности» оборудования.

Если артефакта нет — возраст неизвестен (None), логика плана работает без него.
"""
from __future__ import annotations

import csv
import datetime as dt
import logging
from functools import lru_cache

from .. import config

log = logging.getLogger("channel_meta")

_EPOCH = dt.datetime(1970, 1, 1)
_ARTIFACT = "channel_first_seen.csv"


@lru_cache(maxsize=1)
def _first_seen_map() -> dict:
    fp = config.DATA_DIR / _ARTIFACT
    out: dict[str, dt.datetime] = {}
    if not fp.exists():
        log.warning("нет артефакта возраста оборудования: %s "
                    "(соберите: scripts/build_channel_meta.py)", fp)
        return out
    with fp.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            ch, ts = row.get("ид_канала_данных"), row.get("first_ts")
            if not ch or not ts:
                continue
            try:
                out[str(ch)] = dt.datetime.fromisoformat(ts)
            except ValueError:
                continue
    log.info("channel_meta: загружено %d каналов (первая запись)", len(out))
    return out


def bucket_dt(bucket) -> dt.datetime:
    """Индекс 6ч-бакета -> дата (та же сетка от 1970-01-01, что в features/simclock)."""
    return _EPOCH + dt.timedelta(hours=6 * int(bucket))


def first_seen(channel_id) -> dt.datetime | None:
    return _first_seen_map().get(str(channel_id))


def _naive(when) -> dt.datetime | None:
    if when is None:
        return None
    if hasattr(when, "to_pydatetime"):
        when = when.to_pydatetime()
    if getattr(when, "tzinfo", None) is not None:
        when = when.replace(tzinfo=None)
    return when


def age_days(channel_id, when) -> float | None:
    """Возраст канала в днях на момент `when` (None — первая запись неизвестна)."""
    fs = first_seen(channel_id)
    w = _naive(when)
    if fs is None or w is None:
        return None
    return max(0.0, (w - fs).total_seconds() / 86400.0)


def age_years(channel_id, when) -> float | None:
    d = age_days(channel_id, when)
    return None if d is None else d / 365.25
