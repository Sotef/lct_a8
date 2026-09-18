# -*- coding: utf-8 -*-
"""TTE-пайплайн для слоя 2 «через сколько дней до следующего события».

Событие = СТАРТ СЕРИИ неисправностей (серия = неисправные бакеты канала
с разрывом < 24 ч; разметка — features.add_series_targets).

Контракт валидации (защита от утечек, по требованию ML-команды):
 1. HOLDOUT_START = 2025-07-01. НИЧТО с датой >= HOLDOUT_START не участвует
    в обучении, валидации, подборе порогов и в расчёте статистик признаков.
 2. Внутренний валидационный хвост: 2025-01-01 .. 2025-06-30.
    Модель обучается на строках <= 2024-12-31.
 3. Цензура целей:
    - для строк < HOLDOUT_START наблюдаемое время обрезается на
      min(+30 дней, HOLDOUT_START) — метки НЕ заглядывают в удержанный период;
    - для тестовых строк >= HOLDOUT_START — административная цензура на 30 дней
      и на конец данных.
 4. z_событий пересчитывается ТОЛЬКО по обучающему окну (пер-канальные медианы
    не подглядывают в будущее). Окна панели — строго «прошлое + текущий бакет».
 5. Кампанийные недели (аномально=True) исключаются из всех сплитов.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import features as fe

# ---------------------------------------------------------------------------
# Константы разметки и валидации
# ---------------------------------------------------------------------------
BUCKET_HOURS = fe.BUCKET_HOURS                        # 6 ч
STEPS_PER_DAY = 24 // BUCKET_HOURS                     # 4 бакета в сутках
HORIZON_DAYS = 30.0                                    # административный горизонт
HORIZON_BUCKETS = int(HORIZON_DAYS * STEPS_PER_DAY)    # 120 бакетов = 30 дней

# Границы сплитов (удержанный период — финальная проверка)
TRAIN_END = pd.Timestamp("2024-12-31")          # строки <= этой даты идут в обучение
VAL_START = pd.Timestamp("2025-01-01")          # внутренняя валидация (модельный выбор)
HOLDOUT_START = pd.Timestamp("2025-07-01")      # удержанный период: H2-2025 + 2026

# Точки сетки времени (дни) для кривой выживаемости и метрик
EVAL_TIMES = np.array([0.25, 0.5, 1.0, 2.0, 3.0, 7.0, 14.0, 30.0])
EVAL_STEPS = np.clip(np.round(EVAL_TIMES * STEPS_PER_DAY), 1, HORIZON_BUCKETS).astype(int)

# Колонки, которые нельзя подавать модели (цели/идентификаторы/служебные)
DROP_COLS = [
    "ид_канала_данных", "бакет", "дата", "год_неделя", "аномально",
    "ид_объект", "тип_датчика", "серия_старт", "дни_до_серии", "дни_класс",
    "event_flag", "obs_buckets", "obs_days", "event_time_days",
    "_next_start_bucket", "цель_6ч", "цель_12ч", "цель_24ч", "цель_48ч",
] + [f"цель_серии_{n}" for n in fe.HORIZONS]


def hour_ns() -> int:
    return BUCKET_HOURS * 3600 * 10 ** 9
def load_panel() -> pd.DataFrame:
    """Загружает кэшированный суб-суточный панель канал x 6ч-бакет."""
    fp = fe.DATASET / "subdaily_panel_wear_6h.csv"
    df = pd.read_csv(fp, dtype={"ид_канала_данных": str, "ид_объект": str})
    return df


def refit_z_train_only(panel: pd.DataFrame) -> pd.DataFrame:
    """Пересчёт z_событий по обучающим строкам (<= TRAIN_END, вне кампаний).

    Панель из features.py считает пер-канальную медиану/IQR по ВСЕМ годам —
    это утечка (статистика канала подглядывает в тест). Пересчитываем строго
    по обучающему окну и применяем те же параметры ко всем строкам.
    """
    clean = panel[~panel["аномально"] & (pd.to_datetime(panel["дата"]) <= TRAIN_END)]
    med = clean.groupby("ид_канала_данных")["событий"].median()
    iqr = (clean.groupby("ид_канала_данных")["событий"].quantile(0.75)
           - clean.groupby("ид_канала_данных")["событий"].quantile(0.25))
    out = panel.copy()
    out["z_событий"] = ((out["событий"] - out["ид_канала_данных"].map(med)) /
                        (out["ид_канала_данных"].map(iqr) + 1e-6))
    return out


def add_series_context(panel: pd.DataFrame, event_col: str = "неисправностей") -> pd.DataFrame:
    """Серийная разметка и контекст «давности» по колонке события event_col.

    Событие = первый бакет серии (разрыв < fe.SERIES_GAP = 24 ч между бакетами
    с event_col > 0). Генерирует канонические колонки (имена не зависят от
    event_col, чтобы пайплайн был общим; по умолчанию эквивалентно
    features.add_series_targets):
      - серия_старт, дни_до_серии, цель_серии_{6ч|12ч|24ч|48ч};
      - _next_start_bucket — бакет следующего старта серии (inf, если нет);
      - дни_с_посл_неиспр — дней с последнего события (0 на бакете события;
        смотрит строго в прошлое);
      - дни_с_посл_старта — дней с последнего старта серии (прошлое);
      - в_серии_прокси — признак «недавнее событие» (прошлое, 1/0).
    """
    out = panel.copy()
    out = out.sort_values(["ид_канала_данных", "бакет"]).reset_index(drop=True)
    bucket = out["бакет"].to_numpy(dtype=np.int64)
    ev = (out[event_col].to_numpy(dtype=np.float64) > 0)
    NEG = -2 ** 62
    groups = out.groupby("ид_канала_данных", sort=False).indices

    # предыдущий бакет события cтрого раньше текущего (для старта серии)
    prev = np.full(len(out), NEG, dtype=np.int64)
    for sl in groups.values():
        sl = np.asarray(sl)
        b = bucket[sl]
        eb = b[ev[sl]]
        if not len(eb):
            continue
        i = np.searchsorted(eb, b, side="left") - 1
        pb = np.where(i >= 0, eb[np.maximum(i, 0)], NEG)
        same = (i >= 0) & (eb[np.maximum(i, 0)] == b)
        i2 = np.where(same, i - 1, i)
        pb2 = np.where(i2 >= 0, eb[np.maximum(i2, 0)], NEG)
        prev[sl] = pb2

    out["серия_старт"] = (ev & ((bucket - prev) > fe.SERIES_GAP)).astype(int)

    # следующий старт серии cтрого в будущем
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
    out["дни_до_серии"] = np.where(np.isfinite(dist), dist / STEPS_PER_DAY, np.nan)
    for name, k in fe.HORIZONS.items():
        out[f"цель_серии_{name}"] = (dist <= k).astype(int)
    out.loc[out["аномально"], [f"цель_серии_{n}" for n in fe.HORIZONS]] = np.nan
    out["_next_start_bucket"] = next_start

    # давность последнего события и старта серии (только прошлое)
    last_evf = np.full(len(out), NEG, dtype=np.int64)
    for sl in groups.values():
        sl = np.asarray(sl)
        b = bucket[sl]
        eb = b[ev[sl]]
        if not len(eb):
            continue
        i = np.searchsorted(eb, b, side="right") - 1
        last_evf[sl] = np.where(i >= 0, eb[np.maximum(i, 0)], NEG)

    starts = (out["серия_старт"].to_numpy() == 1)
    last_s = np.full(len(out), NEG, dtype=np.int64)
    for sl in groups.values():
        sl = np.asarray(sl)
        b = bucket[sl]
        sb = b[starts[sl]]
        if not len(sb):
            continue
        i = np.searchsorted(sb, b, side="right") - 1
        last_s[sl] = np.where(i >= 0, sb[np.maximum(i, 0)], NEG)

    msk_f = last_evf > NEG
    msk_s = last_s > NEG
    out["дни_с_посл_неиспр"] = np.where(msk_f,
                                        (bucket - np.maximum(last_evf, 0)) / STEPS_PER_DAY, np.nan)
    out["дни_с_посл_старта"] = np.where(msk_s,
                                        (bucket - np.maximum(last_s, 0)) / STEPS_PER_DAY, np.nan)
    out["в_серии_прокси"] = (msk_f & ((bucket - np.maximum(last_evf, 0)) <= fe.SERIES_GAP)).astype(np.int8)
    return out


def add_tte_labels(subjects: pd.DataFrame) -> pd.DataFrame:
    """Правая цензура + наблюдаемое время до следующего старта серии.

    Правила:
      - событие = следующий старт серии известен И лежит в окне наблюдения;
      - окно = min(бакет + HORIZON_BUCKETS, конец данных) и для строк до
        HOLDOUT_START дополнительно min(., бакет HOLDOUT_START) — метки
        не заглядывают в удержанный период;
      - obs_buckets = расстояние до события (событие) или длина окна (цензура);
        obs_days = obs_buckets / STEPS_PER_DAY.
    """
    out = subjects.copy()
    b = out["бакет"].to_numpy(dtype=np.int64)
    nb = out["_next_start_bucket"].to_numpy(dtype=np.float64)
    dt = pd.to_datetime(out["дата"])
    hn = hour_ns()

    end_bucket = int(b.max())
    hold_bucket = int(HOLDOUT_START.value // hn)

    window_end = np.minimum(b + HORIZON_BUCKETS, end_bucket)
    pre_hold = (dt < HOLDOUT_START).to_numpy()
    window_end = np.where(pre_hold, np.minimum(window_end, hold_bucket), window_end)

    event = np.isfinite(nb) & (nb <= window_end)
    obs = np.where(event, nb - b, window_end - b).astype(np.int64)
    obs = np.maximum(obs, 1)

    out["event_flag"] = event.astype(np.int8)
    out["obs_buckets"] = obs
    out["obs_days"] = obs / STEPS_PER_DAY
    return out


def split_subjects(subjects: pd.DataFrame):
    """Временной сплит с исключением кампаний: (train, val, holdout).

    - train:    дата <= TRAIN_END
    - val:      TRAIN_END < дата < HOLDOUT_START (внутренняя валидация)
    - holdout:  дата >= HOLDOUT_START (никак не используется до финальной оценки)
    Кампанийные недели (аномально) исключены из всех сплитов.
    """
    s = subjects[~subjects["аномально"]].copy()
    dt = pd.to_datetime(s["дата"])
    train = s[dt <= TRAIN_END]
    val = s[(dt > TRAIN_END) & (dt < HOLDOUT_START)]
    holdout = s[dt >= HOLDOUT_START]
    return train, val, holdout
def sample_subjects(subjects: pd.DataFrame, n_starts: int = 20_000,
                    n_fault: int = 15_000, n_nonfault: int = 15_000,
                    seed: int = 42) -> pd.DataFrame:
    """Сбалансированная выборка субъектов (для обучения/валидации).

    Стратификация по состоянию строки: старты серий (якоря событий),
    неисправные не-старты (внутри серий), прочие (тревоги/шум). Без повторов.
    """
    rng = np.random.default_rng(seed)
    starts = subjects[subjects["серия_старт"] == 1]
    faults = subjects[(subjects["серия_старт"] != 1) & (subjects["неисправностей"] > 0)]
    rest = subjects[~subjects.index.isin(starts.index.union(faults.index))]
    picks = []
    for dfx, n in ((starts, n_starts), (faults, n_fault), (rest, n_nonfault)):
        if n is None or n <= 0 or len(dfx) == 0:
            continue
        n = min(n, len(dfx))
        picks.append(dfx.iloc[rng.choice(len(dfx), size=n, replace=False)])
    if not picks:
        return subjects.iloc[0:0].copy()
    out = pd.concat(picks)
    return out.sample(frac=1.0, random_state=seed).reset_index(drop=True)


def sample_holdout(subjects: pd.DataFrame, n_rows: int = 30_000,
                   seed: int = 7) -> pd.DataFrame:
    """Случайная выборка удержанных строк для финальной оценки (стратиф. по году)."""
    rng = np.random.default_rng(seed)
    dt = pd.to_datetime(subjects["дата"])
    year = dt.dt.year
    n = min(n_rows, len(subjects))
    prop = subjects.groupby(year).size() / len(subjects)
    picks = []
    for y, w in prop.items():
        k = int(np.floor(n * w))
        idx = subjects.index[year == y]
        if k > 0 and len(idx) > 0:
            k = min(k, len(idx))
            pos = rng.choice(len(idx), size=k, replace=False)
            picks.append(subjects.loc[idx[pos]])
    out = pd.concat(picks) if picks else subjects.iloc[0:0]
    return out.sample(frac=1.0, random_state=seed).reset_index(drop=True)


def expand_person_time(subjects: pd.DataFrame, X_cols, horizon_buckets: int,
                       fixed_horizon: bool = False):
    """Развёртка субъектов в person-time (шаги 1..K).

    Для обучения (fixed_horizon=False): K = obs_buckets; метка = 1 в шаге события.
    Для предсказания кривой (fixed_horizon=True): K = horizon_buckets для всех.
    Возвращает (X_pt, y). X_pt — фичи субъекта (заморожены на t0) + признаки шага.
    """
    K = np.full(len(subjects), horizon_buckets, dtype=np.int64) if fixed_horizon \
        else subjects["obs_buckets"].to_numpy(dtype=np.int64).clip(min=1)
    n = len(subjects)
    reps = np.repeat(np.arange(n, dtype=np.int64), K)
    step = np.concatenate([np.arange(1, k + 1, dtype=np.int64) for k in K])
    step = np.ascontiguousarray(step)

    X = subjects[X_cols].iloc[reps].reset_index(drop=True)
    X["шаг"] = step

    ts = ((subjects["бакет"].to_numpy(dtype=np.int64)[reps] + step) * hour_ns()
          ).astype("datetime64[ns]")
    dts = pd.Series(ts)
    X["час_шага"] = dts.dt.hour
    X["день_недели_шага"] = dts.dt.dayofweek
    X["месяц_шага"] = dts.dt.month
    X["доля_горизонта"] = step / float(horizon_buckets)

    if fixed_horizon:
        return X, None
    ev = subjects["event_flag"].to_numpy(dtype=np.int8)[reps]
    y = ((ev == 1) & (step == K[reps])).astype(np.int8)
    return X, y


def subject_features(subjects: pd.DataFrame) -> list:
    """Список колонок-фич: числовые признаки панели минус цели/служебные + контекст серий."""
    return [c for c in subjects.columns
            if c not in DROP_COLS and pd.api.types.is_numeric_dtype(subjects[c])]


def make_surv_struct(event_flag, time_days):
    """Структурированная матрица sksurv [(event, time)]."""
    return np.rec.fromarrays(
        [np.asarray(event_flag, dtype=bool), np.asarray(time_days, dtype=np.float64)],
        names="event,time",
    )