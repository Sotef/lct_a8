# -*- coding: utf-8 -*-
"""Переиспользуемые функции чтения данных журналов СМВУ.

Используется ноутбуками EDA (research/dataset/*.ipynb) и скриптами.
Вынесено в .py, чтобы код чтения не дублировался в каждой ячейке.
"""
from __future__ import annotations

import os
import pathlib
from typing import Iterable, Iterator, Optional

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
DATASET_DIR = HERE / "dataset"
EXTRACTED_DIR = DATASET_DIR / "extracted"

# Устойчивое определение папки dataset при произвольном cwd Jupyter
def find_dataset_dir() -> pathlib.Path:
    cands = [
        pathlib.Path.cwd() / "dataset",
        pathlib.Path.cwd() / "research" / "dataset",
        DATASET_DIR,
    ]
    p = pathlib.Path.cwd().resolve()
    for _ in range(6):
        cands.append(p / "dataset")
        p = p.parent
    for cand in cands:
        if cand.exists() and (cand / "extracted").exists():
            return cand
    return DATASET_DIR


def load_ref_channels(ref_csv: Optional[str] = None) -> pd.DataFrame:
    """Справочник каналов: ид_канала_данных, подсистема, тип датчика, тег, название."""
    fp = pathlib.Path(ref_csv) if ref_csv else find_dataset_dir() / "справочник_каналов_датчиков.csv"
    df = pd.read_csv(fp, sep=",", dtype=str, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].astype(str).str.strip()
    return df


def load_ref_objects(ref_csv: Optional[str] = None) -> pd.DataFrame:
    """Справочник объектов: иерархия диспетчера."""
    fp = pathlib.Path(ref_csv) if ref_csv else find_dataset_dir() / "справочник_объектов_диспетчер.csv"
    df = pd.read_csv(fp, sep=",", dtype=str, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    return df


def journal_files(extracted_dir: Optional[pathlib.Path] = None) -> list[pathlib.Path]:
    """CSV журналов по годам, отсортированные."""
    d = pathlib.Path(extracted_dir) if extracted_dir else find_dataset_dir() / "extracted"
    return sorted(d.glob("ext-journal-*.csv"))


def read_chunks(fp, cols: Optional[Iterable[str]] = None, chunksize: int = 2_000_000) -> Iterator[pd.DataFrame]:
    """Читает CSV журнала чанками; отфильтровывает повторные строки-заголовки.

    В файле 2025 (склейка двух выгрузок) заголовок повторяется в середине файла,
    что ломает парсинг — здесь такие строки отбрасываются.
    """
    requested = list(cols) if cols is not None else None
    usecols = requested
    drop_id = False
    if usecols is not None and "ид_события" not in usecols:
        usecols = ["ид_события", *usecols]
        drop_id = True
    kw = dict(sep=",", dtype=str, low_memory=False, chunksize=chunksize, on_bad_lines="skip")
    if usecols:
        kw["usecols"] = usecols
    reader = pd.read_csv(fp, **kw)
    for chunk in reader:
        if "ид_события" in chunk.columns:
            mask = chunk["ид_события"].ne("ид_события")
            chunk = chunk[mask]
        if drop_id and "ид_события" in chunk.columns:
            chunk = chunk.drop(columns=["ид_события"])
        if len(chunk):
            yield chunk


def parse_tag(tag: str) -> dict:
    """Разбор тега инженерной системы 'p1-p2.p3.p4.p5.' → словарь."""
    import re
    parts = re.split(r"[.\-]+", str(tag).strip("."))
    out = {"p1": None, "p2": None, "p3": None, "p4": None, "p5": None}
    for i, v in enumerate(parts):
        if i < 5:
            out[f"p{i + 1}"] = v if v else None
    return out


def is_numeric_value(x) -> bool:
    """Является ли значение датчика числовым показанием."""
    try:
        float(str(x).replace(",", "."))
        return True
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Календарь «известных кампаний» — аномальные периоды проверок/кампаний
# ---------------------------------------------------------------------------
# Формат: (год_неделя_начала, год_неделя_конца, комментарий).
# Эти периоды НЕ являются реальными авариями/отказами, а вызваны
# внешними регуляторными/методическими причинами:
#   * ППР №1479 (вступление в силу 01.01.2021) + новые СП 484/485/486 МЧС
#     (вступление в силу с 01.03.2021) → массовая кампания проверки
#     и ремонта дымовых извещателей весной 2021 (пик 2021W17–W22,
#     ~990 тыс. тревог дыма = ~85% всех тревог дыма за 8 лет).
#   * 2026W23 — локальный всплеск тревог (преимущественно дым), природа
#     подлежит проверке; по умолчанию помечается как «возможная кампания».
CAMPAIGN_WEEKS = [
    (202116, 202123, "Переходный период до/после пика проверок 2021 (ППР-1479/СП 484-486)"),
    (202117, 202122, "Пик кампании проверок дымовых извещателей апрель-май 2021"),
    (202623, 202623, "Локальный всплеск 2026W23 — проверить природу"),
]

# Недели, исключаемые из обучающих/валидационных/тестовых сплитов по умолчанию.
# Вырезаем весь «проверочный» юнит (включая переходные недели), чтобы модель
# не выучивала эффект кампании как «поведение датчиков».
EXCLUDE_WEEKS_DEFAULT = {202116, 202117, 202118, 202119, 202120, 202121, 202122, 202123}


def week_is_campaign(week: int, campaigns: Optional[list] = None) -> bool:
    """True, если ISO-неделя (год*100+неделя) попадает в одну из кампаний."""
    if campaigns is None:
        campaigns = CAMPAIGN_WEEKS
    for w1, w2, _ in campaigns:
        if w1 <= week <= w2:
            return True
    return False


def add_campaign_flags(weekly: pd.DataFrame, week_col: str = "год_неделя") -> pd.DataFrame:
    """Добавляет колонку is_campaign для таблицы недельной сводки."""
    df = weekly.copy()
    df["is_campaign"] = df[week_col].astype(int).map(week_is_campaign)
    return df


def filter_clean_weeks(weekly: pd.DataFrame, week_col: str = "год_неделя",
                       excl: Optional[set] = None) -> pd.DataFrame:
    """Оставляет только «чистые» недели (вне кампаний/исключаемых)."""
    if excl is None:
        excl = EXCLUDE_WEEKS_DEFAULT
    w = weekly[week_col].astype(int)
    return weekly[~w.isin(excl) & ~w.map(lambda x: week_is_campaign(x))].copy()