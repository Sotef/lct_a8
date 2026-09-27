# -*- coding: utf-8 -*-
"""Фаза D: отчёт соответствия «букве ТЗ» (P(≤24ч), Precision≥0.7).

Запуск (из research/):
    .venv\\Scripts\\python.exe report_tz_compliance.py

Генерирует docs/TZ_COMPLIANCE_REPORT.md — честные формулировки «достижимо /
частично / недостижимо» с числами по holdout ≥ 2025-07-01 (20k субъектов).
Резервный сценарий, если заказчик настоит на 24ч-постановке (ML_PLAN.md Часть III, Фаза D).
"""
from __future__ import annotations

import pathlib

import pandas as pd

import inference_contract as ic

HERE = pathlib.Path(__file__).resolve().parent
MODELS = HERE / "models"
DOCS = HERE / "docs"


def task_report(task: str) -> dict:
    fp = MODELS / f"tte_{task}_holdout.parquet"
    df = pd.read_parquet(fp)
    y24 = ((df["event_flag"] == 1) & (df["obs_days"] <= 1.01)).to_numpy(int)
    p24 = df["p24"].to_numpy(float)
    y30 = ((df["event_flag"] == 1) & (df["obs_days"] <= 30.01)).to_numpy(int)
    from tte_experiments import pr_at_horizon
    pr24 = pr_at_horizon(y24, p24)
    pr30 = pr_at_horizon(y30, df["risk30"].to_numpy(float))
    t50 = ic.top_k(df, "p24", 50, y24)
    t100 = ic.top_k(df, "p24", 100, y24)
    t2000 = ic.top_k(df, "p24", 2000, y24)
    bk = ic.best_k_precision(df, "p24", y24, min_precision=0.7)
    return {
        "task": task,
        "n": len(df),
        "base24%": pr24["base"] * 100,
        "pr_auc_24": pr24["pr_auc"],
        "prec@50": t50["precision"], "prec@100": t100["precision"],
        "recall@2000": t2000["recall"],
        "K_max@prec>=.7": bk["K"] if bk else None,
        "recall@K_max": bk["recall"] if bk else None,
        "base30%": pr30["base"] * 100,
        "pr_auc_30": pr30["pr_auc"],
        "events24": int(y24.sum()),
    }


VERDICT = {
    "wear": "ДОСТИЖИМО: база 12.7%, порог 24ч выходит на Precision 0.7 с Recall≈0.8; "
            "24ч-прецизия — рабочий инструмент (K≈3 тыс.).",
    "fire": "ЧАСТИЧНО: PR-AUC(24ч) 0.42 и top-152 → Prec 0.70 (recall 0.35), но это «продолжение "
            "подтверждённого задымления», а не предсказание первого события (аудит честности §21.6).",
    "access": "НЕДОСТИЖИМО на 24ч (база 1.0%, PR-AUC 0.03): нет СКУД/допусков (ground-truth). "
              "Резерв: топ-K по калиброванному risk30 + медиана дней.",
    "sensor": "НЕДОСТИЖИМО на 24ч (база 0.3%, PR-AUC 0.012): редкие события; нет журнала ОДС/ремонтов. "
              "Резерв: RUL-распределения + план замен (RBAM).",
}


def main() -> None:
    lines = []
    lines.append("# Соответствие «букве ТЗ» (fallback, Фаза D) — отчёт 20.09.2026")
    lines.append("")
    lines.append("Показатели P(событие ≤ 24ч) и Precision/Recall на holdout ≥ 2025-07-01 "
                 "(20k субъектов). Резервный сценарий; ядро продукта — риск-портфель (ML_PLAN.md Часть III).")
    lines.append("")
    rows = []
    for task in ("fire", "access", "sensor", "wear"):
        r = task_report(task)
        rows.append(r)
        lines.append("")
        lines.append(f"## {task} — {VERDICT[task]}")
        lines.append("")
        lines.append(f"- строк holdout: {r['n']:,} · событий в 24ч: {r['events24']}")
        lines.append(f"- база 24ч: **{r['base24%']:.2f}%** · PR-AUC(24ч): {r['pr_auc_24']:.3f} · "
                     f"prec@50: {r['prec@50']:.2f} · prec@100: {r['prec@100']:.2f} · recall@2000: {r['recall@2000']:.2f}")
        lines.append(f"- K@prec≥0.7 (24ч): {r['K_max@prec>=.7'] if r['K_max@prec>=.7'] else '—'} · "
                     f"recall там: {r['recall@K_max']:.2f}" if r["recall@K_max"] else
                     f"- K@prec≥0.7 (24ч): —")
        lines.append(f"- база 30д: {r['base30%']:.1f}% · PR-AUC(30д): {r['pr_auc_30']:.3f}")
    lines.append("")
    lines.append("## Сводная таблица")
    lines.append("")
    lines.append(pd.DataFrame(rows).round(3).to_markdown(index=False))
    lines.append("")
    lines.append("Вывод: формально «ТЗ-строгий» сценарий рабочий только у wear; "
                 "fire — на топ-K с оговоркой о «продолжении»; access/sensor — недостижимы "
                 "на 24ч без внешних данных (СКУД/ОДС). Контрпредложение — риск-портфель "
                 "(RISK_PIVOT_REPORT.md).")
    out = DOCS / "TZ_COMPLIANCE_REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("saved:", out)


if __name__ == "__main__":
    main()