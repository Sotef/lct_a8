# -*- coding: utf-8 -*-
"""Метаданные задач прогнозирования (зеркало research/rebuild_task_panels.py + task_tte.py).

Задача -> {event_col, типы датчиков, extra_cols (панельные счётчики), панель}.
Файл — единственное место истины для сервиса; ML-логика остаётся в research.
"""
from __future__ import annotations

from .research_bridge import module as _m

# Семантические значения журнала (research/features.py)
SMOKE_ALARM_VALUES = set(_m("features").SMOKE_ALARM_VALUES)
MANUAL_ALARM_VALUES = set(_m("features").MANUAL_ALARM_VALUES)
OPEN_LOOP_VALUES = set(_m("features").OPEN_LOOP_VALUES)
FAULT_STATUSES = set(_m("features").FAULT_STATUSES)

WEAR_TYPES = ["Состояние насоса", "Состояние вентилятора", "Состояние фазы"]

TASKS = {
    "fire": {
        "desc": "Пожарный риск",
        "event_col": "серьёзных",
        "types": ["Датчик дыма", "Тепловой датчик", "Ручной извещатель",
                  "Датчик температуры"],
        "panel": "subdaily_panel_fire6h.csv",
        "calibrated": False,
        "severity_default": 0.85,
    },
    "access": {
        "desc": "Несанкционированный доступ",
        "event_col": "тревог",
        "types": ["КД Дверь", "Датчик движения", "КД АВ", "КД Люк", "Стекло",
                  "9-секционный люк"],
        "panel": "subdaily_panel_access6h.csv",
        "calibrated": True,
        "severity_default": 0.60,
    },
    "sensor": {
        "desc": "Отказ датчика",
        "event_col": "неисправностей",
        "types": ["Датчик дыма", "Датчик движения", "Датчик температуры",
                  "Газовый датчик", "КД Дверь", "КД АВ", "КД Люк",
                  "Тепловой датчик", "Стекло", "Датчик затопления"],
        "panel": "subdaily_panel_sensor6h.csv",
        "calibrated": False,
        "severity_default": 0.55,
    },
    "wear": {
        "desc": "Износ инфраструктуры",
        "event_col": "неисправностей",
        "types": WEAR_TYPES,
        "panel": "subdaily_panel_wear_6h.csv",
        "calibrated": False,
        "severity_default": 0.60,
    },
}

ALL_TASKS = list(TASKS)


def _channels_of(ref_channels, types) -> set:
    return set(ref_channels.loc[ref_channels["тип_датчика"].isin(types),
                                "ид_канала_данных"])


def extra_specs(ref_channels) -> dict:
    """Все панельные extra_cols всех задач (для ОДНОГО прохода по журналу)."""
    smoke = _channels_of(ref_channels, ["Датчик дыма"])
    manual = _channels_of(ref_channels, ["Ручной извещатель"])
    heat = _channels_of(ref_channels, ["Тепловой датчик"])
    door = _channels_of(ref_channels, ["КД Дверь"])
    motion = _channels_of(ref_channels, ["Датчик движения"])
    sensor_all = _channels_of(ref_channels, TASKS["sensor"]["types"])
    return {
        "задымлений": {"kind": "value_by_type", "count_channels": True,
                       "channels": smoke, "values": SMOKE_ALARM_VALUES},
        "серьёзн_ручной": {"kind": "value_by_type", "count_channels": True,
                           "channels": manual, "values": MANUAL_ALARM_VALUES},
        "тревог_дым": {"kind": "alarm_by_type", "count_channels": True,
                       "channels": smoke},
        "тревог_тепло": {"kind": "alarm_by_type", "channels": heat},
        "тревог_дверь": {"kind": "alarm_by_type", "count_channels": True,
                         "channels": door},
        "тревог_движение": {"kind": "alarm_by_type", "count_channels": True,
                            "channels": motion},
        "пр_разрывов": {"kind": "value_by_type", "count_channels": True,
                        "channels": sensor_all, "values": OPEN_LOOP_VALUES},
        "неисправн_дым": {"kind": "value_by_type", "count_channels": True,
                          "channels": smoke, "values": FAULT_STATUSES},
    }


def union_channels(ref_channels) -> set:
    """Все каналы всех задач."""
    out = set()
    for cfg in TASKS.values():
        out |= _channels_of(ref_channels, cfg["types"])
    return out


def task_extra_names(task: str) -> list[str]:
    """Имена extra_cols задачи (порядок важен: как в rebuild_task_panels.py)."""
    _names = {
        "fire": ["задымлений", "серьёзн_ручной", "тревог_дым", "тревог_тепло"],
        "access": ["тревог_дверь", "тревог_движение"],
        "sensor": ["пр_разрывов", "неисправн_дым"],
        "wear": [],
    }
    return _names[task]