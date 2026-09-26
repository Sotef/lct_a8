# -*- coding: utf-8 -*-
"""Графики плановых работ ТО/ППР от заказчика (2026) → календарь ISO-недель.

Источник — две xlsx-выгрузки РЭК (read-only кэш в
`dataset/_external/maintenance_plan/`):
  * «График ППР АКМ на 2026г.» — помесячный план снятия/поверки метановых
    датчиков (АКМ) по объектам с точными окнами дат;
  * «График ТО и ТР систем АКМ и ДУ» — регламент ТО/ТР по объектам и видам
    оборудования, отметки в сетке «месяц × объект/оборудование».

Назначение (research + service-адаптер):
  * построить календарь плановых работ (ISO-недели 2026) для маскировки/
    пометки «кампанийных» окон (аналог `data_utils.CAMPAIGN_WEEKS`);
  * отдать нормированный регламент в модуль превентивных заявок сервиса.

ОГРАНИЧЕНИЕ: объекты в графиках анонимизированы как «Объект N» и НЕ связаны
с нашими `ид_объект`/`объект Альфа…` — поэтому календарь глобальный
(по всем объектам), без join на канал. Маппинг нужен от заказчика.
"""
from __future__ import annotations

import pathlib
from typing import Optional

import openpyxl
import pandas as pd

import data_utils as du

HERE = pathlib.Path(__file__).resolve().parent
EXTERNAL = du.find_dataset_dir() / "_external" / "maintenance_plan"

PPR_FILE = EXTERNAL / "grafik_ppr_akm_2026.xlsx"
TO_FILE = EXTERNAL / "grafik_to_tr_akm_du_2026.xlsx"

YEAR = 2026


# --------------------------------------------------------------------------
# Календарь ISO-недель 2026
# --------------------------------------------------------------------------
def month_weeks(year: int = YEAR) -> dict[int, set[int]]:
    """{номер_месяца: множество ISO-недель (год*100+неделя)} для года."""
    dts = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    iso = dts.isocalendar()
    wk = (iso["year"].astype(int) * 100 + iso["week"].astype(int)).to_numpy()
    months = dts.month.to_numpy()
    out: dict[int, set[int]] = {}
    for m in range(1, 13):
        out[m] = sorted(set(wk[months == m].tolist()))
    return out


def weeks_from_dates(d1, d2, year: int = YEAR) -> list[int]:
    """ISO-недели, покрывающие интервал дат [d1, d2] (в пределах года)."""
    if pd.isna(d1) and pd.isna(d2):
        return []
    lo = pd.Timestamp(d1) if pd.notna(d1) else pd.Timestamp(f"{year}-01-01")
    hi = pd.Timestamp(d2) if pd.notna(d2) else lo
    if hi < lo:
        lo, hi = hi, lo
    dts = pd.date_range(lo, hi, freq="D")
    iso = dts.isocalendar()
    return sorted(set((iso["year"].astype(int) * 100 + iso["week"].astype(int)).tolist()))


# --------------------------------------------------------------------------
# Парсер ППР АКМ (метановые датчики)
# --------------------------------------------------------------------------
def parse_ppr(path: pathlib.Path | None = None) -> pd.DataFrame:
    """«График ППР АКМ» → окна снятия датчиков метана по объектам.

    Колонки: объект, месяц, месяц_имя, кол-во, демонтаж, в_ом, вывоз, сдача,
    окно_начало, окно_конец.
    """
    path = pathlib.Path(path) if path else PPR_FILE
    ws = openpyxl.load_workbook(path, data_only=True).active
    rows = []
    cur_month: Optional[int] = None
    for r in range(10, ws.max_row + 1):   # строка 9 — шапка
        b = ws.cell(row=r, column=2).value      # Месяц проведения ППР
        c = ws.cell(row=r, column=3).value      # Наименование коллектора
        d = ws.cell(row=r, column=4).value      # Кол-во, шт.
        e = ws.cell(row=r, column=5).value      # Начало демонтажа
        f = ws.cell(row=r, column=6).value      # Предоставление в ОМ (строка)
        g = ws.cell(row=r, column=7).value      # Вывоз из ОМ
        h = ws.cell(row=r, column=8).value      # Сдача комиссии
        if isinstance(b, str) and b.strip().lower() in _MONTHS:
            cur_month = _MONTHS[b.strip().lower()]
        if c is None and d is None:
            continue
        rows.append({
            "объект": str(c).strip() if c is not None else None,
            "месяц": cur_month,
            "месяц_имя": b.strip() if isinstance(b, str) else None,
            "кол-во": int(d) if isinstance(d, (int, float)) else None,
            "демонтаж": pd.to_datetime(e) if pd.notna(e) else pd.NaT,
            "в_ом": str(f).strip() if f is not None else None,
            "вывоз": pd.to_datetime(g) if pd.notna(g) else pd.NaT,
            "сдача": pd.to_datetime(h) if pd.notna(h) else pd.NaT,
        })
    df = pd.DataFrame(rows)
    # окно плановой работы: [демонтаж, сдача]; фолбэк — границы месяца
    df["окно_начало"] = df["демонтаж"]
    df["окно_конец"] = df["сдача"]
    for i, row in df.iterrows():
        if pd.isna(row["окно_начало"]) and pd.notna(row["месяц"]):
            df.at[i, "окно_начало"] = pd.Timestamp(f"{YEAR}-{int(row['месяц']):02d}-01")
        if pd.isna(row["окно_конец"]) and pd.notna(row["окно_начало"]):
            m = int(row["месяц"]) if pd.notna(row["месяц"]) else pd.Timestamp(row["окно_начало"]).month
            df.at[i, "окно_конец"] = (pd.Timestamp(f"{YEAR}-{m:02d}-01")
                                      + pd.offsets.MonthEnd(0))
    return df


# Месяцы (рус.) → номер, для forward-fill объединённых ячеек в ППР-графике
_MONTHS = {
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4, "май": 5, "июнь": 6,
    "июль": 7, "август": 8, "сентябрь": 9, "октябрь": 10, "ноябрь": 11,
    "декабрь": 12,
}


# --------------------------------------------------------------------------
# Парсер графика ТО/ТР АКМ и ДУ
# --------------------------------------------------------------------------
_MONTH_COLS = list(range(7, 19))   # G..R = янв..дек


def parse_to(path: pathlib.Path | None = None) -> pd.DataFrame:
    """«График ТО и ТР АКМ и ДУ» → отметки ТО/ТР по объектам и оборудованию.

    Колонки: объект, вид_оборудования, кол-во, ед, месяц, вид_работы.
    """
    path = pathlib.Path(path) if path else TO_FILE
    ws = openpyxl.load_workbook(path, data_only=True).active
    rows = []
    cur_obj: Optional[int] = None
    for r in range(6, ws.max_row + 1):
        b = ws.cell(row=r, column=2).value      # № п.п. (номер объекта)
        c = ws.cell(row=r, column=3).value      # 'Объект' / 'к-р Ясенево'
        d = ws.cell(row=r, column=4).value      # Вид оборудования (в шапке — «Марка»)
        e = ws.cell(row=r, column=5).value      # Кол-во
        f = ws.cell(row=r, column=6).value      # ед.
        if isinstance(b, str) and b.strip() == "№ п.п.":
            continue                            # повторная шапка
        if isinstance(b, (int, float)) and not isinstance(b, bool):
            cur_obj = int(b)
        if cur_obj is None:
            continue
        equip = None
        if isinstance(d, str) and d.strip() and d.strip() != "Марка":
            equip = d.strip()
        for mi, col in enumerate(_MONTH_COLS, start=1):
            v = ws.cell(row=r, column=col).value
            if isinstance(v, str) and "ТО" in v.upper():
                rows.append({
                    "объект": f"Объект {cur_obj}" if c != "к-р Ясенево" else "к-р Ясенево",
                    "вид_оборудования": equip,
                    "кол-во": int(e) if isinstance(e, (int, float)) else None,
                    "ед": str(f).strip() if f is not None else None,
                    "месяц": mi,
                    "вид_работы": "ТО+ТР" if "ТР" in v.upper() else "ТО",
                })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Календарь плановых работ в ISO-неделях
# --------------------------------------------------------------------------
def planned_work_weeks(ppr: Optional[pd.DataFrame] = None,
                       to: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Длинная таблица: (год_неделя, источник, объект, вид_работы, месяц)."""
    ppr = parse_ppr() if ppr is None else ppr
    to = parse_to() if to is None else to
    mw = month_weeks(YEAR)
    rows = []
    for _, r in ppr.iterrows():
        weeks = weeks_from_dates(r["окно_начало"], r["окно_конец"])
        if not weeks and pd.notna(r["месяц"]):
            weeks = mw[int(r["месяц"])]
        for wk in weeks:
            rows.append({"год_неделя": wk, "источник": "ППР_АКМ",
                         "объект": r["объект"], "вид_работы": "ППР+поверка",
                         "месяц": int(r["месяц"]) if pd.notna(r["месяц"]) else None})
    for _, r in to.iterrows():
        for wk in mw[int(r["месяц"])]:
            rows.append({"год_неделя": wk, "источник": "ТО_ДУ_АКМ",
                         "объект": r["объект"], "вид_работы": r["вид_работы"],
                         "месяц": int(r["месяц"])})
    out = pd.DataFrame(rows)
    return out.sort_values(["год_неделя", "источник", "объект"]).reset_index(drop=True)


def planned_week_set(weeks: Optional[pd.DataFrame] = None) -> set[int]:
    """Множество ISO-недель 2026, в которые есть хоть какие-то плановые работы."""
    weeks = planned_work_weeks() if weeks is None else weeks
    return set(weeks["год_неделя"].astype(int).tolist())


def build_and_save(out_dir: Optional[pathlib.Path] = None) -> dict[str, pathlib.Path]:
    """Считает и сохраняет артефакты в dataset/ (идемпотентно)."""
    out_dir = pathlib.Path(out_dir) if out_dir else du.find_dataset_dir()
    ppr = parse_ppr()
    to = parse_to()
    weeks = planned_work_weeks(ppr, to)
    f_ppr = out_dir / "planned_work_ppr_2026.csv"
    f_to = out_dir / "planned_work_to_2026.csv"
    f_wk = out_dir / "planned_work_weeks_2026.csv"
    ppr.to_csv(f_ppr, index=False, encoding="utf-8-sig")
    to.to_csv(f_to, index=False, encoding="utf-8-sig")
    weeks.to_csv(f_wk, index=False, encoding="utf-8-sig")
    return {"ppr": f_ppr, "to": f_to, "weeks": f_wk}


if __name__ == "__main__":
    saved = build_and_save()
    for k, v in saved.items():
        print(f"{k}: {v}")
    ppr, to = parse_ppr(), parse_to()
    wk = planned_work_weeks(ppr, to)
    print(f"ППР: объектов={ppr['объект'].nunique()}, датчиков={ppr['кол-во'].sum()}")
    print(f"ТО: объектов={to['объект'].nunique()}, отметок ТО/ТР={len(to)}")
    print(f"Недель с плановыми работами: {len(planned_week_set(wk))} из 53")
    print(sorted(planned_week_set(wk)))

