# -*- coding: utf-8 -*-
"""Форматирование потоковых данных под модели (п.2-4 BACKEND_SPEC §3).

Цепочка (5 шагов) для одной задачи:
  1. панель 6ч (канал x бакет): make_subdaily_panel(precomputed=cache_raw);
  2. z_событий по TRAIN-статистикам (z_stats_<task>.csv) — без «заглядывания» в 2026;
  3. серийный контекст: tte.add_series_context(event_col=<задача>);
  4. субъекты текущего бакета + subject features (колонки == обучению, порядок тот же);
  5. инференс (в inference.py / inference_contract).

Результат гарантированно имеет те же имена/порядок фич, что и обучение:
сверка с research/_features_schema.json (X_cols задачи) в каждой сборке.
"""
from __future__ import annotations

import json
import logging
import pathlib

import numpy as np
import pandas as pd

from .. import config
from .. import task_cfg
from ..adapters.journal import bucket_to_timestamp
from ..research_bridge import module as _m

log = logging.getLogger("features")


class PanelBuildError(RuntimeError):
    pass


def _load_features_schema() -> dict:
    fp = config.DATA_DIR / "_features_schema.json"
    if not fp.exists():
        raise PanelBuildError(f"нет схемы фич: {fp}")
    return json.loads(fp.read_text(encoding="utf-8"))


def task_event_col(task: str) -> str:
    return task_cfg.TASKS[task]["event_col"]


def _build_channel_sets(ref_channels: pd.DataFrame) -> dict:
    """Те же спецификации extra_cols, что research/rebuild_task_panels."""
    def ch_of(*types) -> set:
        return set(ref_channels.loc[ref_channels["тип_датчика"].isin(types),
                                    "ид_канала_данных"])
    smoke = ch_of("Датчик дыма")
    manual = ch_of("Ручной извещатель")
    heat = ch_of("Тепловой датчик")
    door = ch_of("КД Дверь")
    motion = ch_of("Датчик движения")
    sensor_all = ch_of(*task_cfg.TASKS["sensor"]["types"])
    fe = _m("features")
    return {
        "задымлений": {"kind": "value_by_type", "count_channels": True,
                       "channels": smoke, "values": fe.SMOKE_ALARM_VALUES},
        "серьёзн_ручной": {"kind": "value_by_type", "count_channels": True,
                           "channels": manual, "values": fe.MANUAL_ALARM_VALUES},
        "тревог_дым": {"kind": "alarm_by_type", "count_channels": True,
                       "channels": smoke},
        "тревог_тепло": {"kind": "alarm_by_type", "channels": heat},
        "тревог_дверь": {"kind": "alarm_by_type", "count_channels": True,
                         "channels": door},
        "тревог_движение": {"kind": "alarm_by_type", "count_channels": True,
                            "channels": motion},
        "пр_разрывов": {"kind": "value_by_type", "count_channels": True,
                        "channels": sensor_all, "values": fe.OPEN_LOOP_VALUES},
        "неисправн_дым": {"kind": "value_by_type", "count_channels": True,
                          "channels": smoke, "values": fe.FAULT_STATUSES},
    }


def load_extra_cols(ref_channels: pd.DataFrame, task: str) -> dict:
    """Extra_cols конкретной задачи (для make_subdaily_panel)."""
    all_specs = _build_channel_sets(ref_channels)
    return {n: all_specs[n] for n in task_cfg.task_extra_names(task)}
def build_subdaily_panel(task: str, raw_parts: list[pd.DataFrame],
                         out_csv: pathlib.Path | None = None) -> pd.DataFrame:
    """Шаг 1: 6ч-панель задачи (100% research/features.make_subdaily_panel)."""
    fe = _m("features")
    ref = fe.du.load_ref_channels()
    cfg = task_cfg.TASKS[task]
    extra = load_extra_cols(ref, task)
    # отбор колонок сырого кэша до «основные + extra задачи» (порядок как в research)
    base_cols = ["ид_канала_данных", "бакет", "событий", "тревог",
                 "неисправностей", "шума"] + task_cfg.task_extra_names(task)
    ch_set = set(ref.loc[ref["тип_датчика"].isin(cfg["types"]),
                         "ид_канала_данных"])
    parts = []
    for part in raw_parts:
        part = part[part["ид_канала_данных"].isin(ch_set)].copy()
        keep = [c for c in base_cols if c in part.columns]
        parts.append(part[keep])
    if not parts:
        raise PanelBuildError(f"[{task}] пустой сырой кэш для панели")
    if sum(len(p) for p in parts) == 0:
        return pd.DataFrame()          # у задачи пока нет событий (живая подача)
    out = fe.DATASET if out_csv is None else pathlib.Path(out_csv)
    try:
        panel = fe.make_subdaily_panel(types=cfg["types"], recompute=False,
                                       out_csv=out, extra_cols=extra, precomputed=parts)
    except KeyError as exc:
        # research-панель рассчитана на полный датасет; в живой подаче на первых бакетах
        # по задаче может ещё не хватать событий/типов каналов — прогноз появится позже
        log.warning("[%s] панель пока не строится (недостаточно данных в бакетах): %s",
                    task, exc, exc_info=True)
        return pd.DataFrame()
    panel["ид_канала_данных"] = panel["ид_канала_данных"].astype(str)
    panel["ид_объект"] = panel["ид_объект"].astype(str)
    return panel


def apply_post_task_features(panel: pd.DataFrame, task: str) -> pd.DataFrame:
    """Деривативы задач (rebuild_task_panels.build_fire/access)."""
    fe = _m("features")
    df = panel.copy()
    if task == "fire":
        df["задым_подтв_об_б"] = (df["каналов_задымлений_об_б"].to_numpy() >= 2).astype(np.int8)
        df = fe._add_bucket_windows(df, ["задым_подтв_об_б"], windows=fe.BUCKET_WINDOWS,
                                    group_col="ид_объект")
        df["серьёзных"] = (((df["задымлений"].to_numpy() > 0)
                            & (df["задым_подтв_об_б"].to_numpy() == 1))
                           | (df["серьёзн_ручной"].to_numpy() > 0)).astype(np.int8)
        df = fe._add_bucket_windows(df, ["серьёзных"], windows=fe.BUCKET_WINDOWS)
    elif task == "access":
        df["дверь_движение_об_б"] = (
            (df["каналов_тревог_дверь_об_б"].to_numpy() > 0)
            & (df["каналов_тревог_движение_об_б"].to_numpy() > 0)).astype(np.int8)
        df = fe._add_bucket_windows(df, ["дверь_движение_об_б"],
                                    windows=fe.BUCKET_WINDOWS, group_col="ид_объект")
    return df


def apply_train_z_stats(panel: pd.DataFrame, task: str) -> pd.DataFrame:
    """Шаг 2: z_событий строго по train-статистикам (research/tte.refit_z_train_only)."""
    zf = config.DATA_DIR / f"z_stats_{task}.csv"
    if not zf.exists():
        raise PanelBuildError(f"нет z-статистик: {zf}")
    zs = pd.read_csv(zf, dtype={"ид_канала_данных": str})
    med = dict(zip(zs["ид_канала_данных"], zs["median"]))
    iqr = dict(zip(zs["ид_канала_данных"], zs["iqr"]))
    out = panel.copy()
    ch = out["ид_канала_данных"].astype(str)
    num = out["событий"].to_numpy(dtype=np.float64)
    m = ch.map(med).to_numpy(dtype=np.float64)
    i = ch.map(iqr).to_numpy(dtype=np.float64)
    out["z_событий"] = (num - m) / (i + 1e-6)
    return out


def apply_series_and_labels(panel: pd.DataFrame, task: str) -> pd.DataFrame:
    """Шаг 3: серийный контекст (событие задачи) + TTE-метки."""
    tte = _m("tte_pipeline")
    out = tte.add_series_context(panel, event_col=task_event_col(task))
    out = tte.add_tte_labels(out)
    return out


def apply_cat_codes(panel: pd.DataFrame, task: str) -> pd.DataFrame:
    """Категориальные коды (маппинг обучения, fallback max+1)."""
    fp = config.DATA_DIR / f"cat_codes_{task}.json"
    if not fp.exists():
        raise PanelBuildError(f"нет cat_codes: {fp}")
    data = json.loads(fp.read_text(encoding="utf-8"))
    obj_map = {str(k): int(v) for k, v in data["ид_объект"].items()}
    type_map = {str(k): int(v) for k, v in data["тип_датчика"].items()}
    obj_new = (max(obj_map.values()) + 1) if obj_map else 0
    type_new = (max(type_map.values()) + 1) if type_map else 0
    out = panel.copy()
    out["ид_объект_code"] = out["ид_объект"].astype(str).map(obj_map).fillna(obj_new).astype(int)
    out["тип_датчика_code"] = out["тип_датчика"].astype(str).map(type_map).fillna(type_new).astype(int)
    return out
def align_to_schema(subjects: pd.DataFrame, task: str,
                    feature_cols: list[str] | None = None) -> pd.DataFrame:
    """Проверяет/выравнивает колонки до X_cols обучения (DROP_COLS как в tte_pipeline)."""
    tte = _m("tte_pipeline")
    if feature_cols is None:
        feature_cols = _load_features_schema().get(task, {}).get("X_cols")
    if not feature_cols:
        raise PanelBuildError(f"[{task}] нет X_cols в схеме фич")
    missing = [c for c in feature_cols if c not in subjects.columns]
    if missing:
        raise PanelBuildError(f"[{task}] отсутствуют фичи: {missing}")
    # только нужные колонки: фичи в порядке обучения + служебные (DROP_COLS)
    service = ["ид_канала_данных", "бакет", "дата", "ид_объект", "тип_датчика",
               "event_flag", "obs_days", "аномально", "год_неделя"]
    keep = feature_cols + [c for c in service if c in subjects.columns]
    out = subjects[keep].copy()
    got = tte.subject_features(out)
    if got != feature_cols:
        raise PanelBuildError(
            f"[{task}] subject_features != X_cols: {len(got)} vs {len(feature_cols)}")
    return out


def build_subjects(task: str, recompute_panel: bool = True,
                   years=("2026",)) -> pd.DataFrame:
    """Полная сборка субъектов задачи из кэша сырых бакетов.

    Порядок шагов повторяет research: панель -> z(train) -> серии -> метки -> коды.
    """
    raw_dir = config.RAW_DIR
    parts = []
    for y in years:
        p = raw_dir / f"buckets_{y}.parquet"
        if not p.exists():
            raise PanelBuildError(f"[{task}] нет кэша сырых бакетов: {p} "
                                  f"— запустите адаптер журнала")
        parts.append(pd.read_parquet(p))
    csv = config.PANEL_DIR / f"subdaily_panel_{task}6h_2026.csv"
    try:
        if recompute_panel or not csv.exists():
            panel = build_subdaily_panel(task, parts, out_csv=csv)
            if panel is None or not len(panel) or "ид_канала_данных" not in panel.columns:
                return pd.DataFrame()
            panel = apply_post_task_features(panel, task)
            panel.to_csv(csv, index=False, encoding="utf-8-sig")
        else:
            panel = pd.read_csv(csv, dtype={"ид_канала_данных": str,
                                            "ид_объект": str})
        if panel is None or not len(panel) or "ид_канала_данных" not in panel.columns:
            # живая подача: на первых бакетах у задачи может ещё не быть событий
            return pd.DataFrame()
        panel = apply_train_z_stats(panel, task)
        panel = apply_series_and_labels(panel, task)
        subjects = apply_cat_codes(panel, task)
        subjects = align_to_schema(subjects, task)
    except KeyError as exc:
        # research-панель/деривативы рассчитаны на полный датасет: в живой подаче
        # на ранних бакетах по задаче может не хватать событий/типов каналов.
        # Прогноз по задаче появится, когда данных накопится достаточно.
        log.warning("[%s] признаки пока не собираются (мало данных): %s", task, exc)
        try:
            csv.unlink(missing_ok=True)      # чтобы не читать неполный кэш панели
        except OSError:
            pass
        return pd.DataFrame()
    return subjects


def subjects_for_bucket(subjects: pd.DataFrame, bucket: int) -> pd.DataFrame:
    """Субъекты конкретного бакета (каналы, активные в этот 6ч-интервал).

    В режиме живой подачи панель на первых бакетах может быть пустой (данных ещё нет) —
    тогда корректно возвращаем пустую выборку, а не падаем с KeyError.
    """
    if subjects is None or not len(subjects) or "бакет" not in subjects.columns:
        return pd.DataFrame()
    return subjects[subjects["бакет"] == bucket].reset_index(drop=True)


def latest_bucket(subjects: pd.DataFrame) -> int:
    if subjects is None or not len(subjects) or "бакет" not in subjects.columns:
        raise PanelBuildError("в панели нет строк — нет данных для прогноза")
    return int(subjects["бакет"].max())


def bucket_to_dt(bucket: int):
    return bucket_to_timestamp(bucket)