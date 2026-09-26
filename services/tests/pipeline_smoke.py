# -*- coding: utf-8 -*-
"""Смоук-тест потокового пайплайна на реальных данных ext-journal-2026.csv.

Проверяет: адаптер (инкрементальный ингвест) -> сырой кэш -> панель задачи ->
z по train-статистикам -> серийный контекст -> субъекты (X_cols == обучению) ->
инференс (p24/risk30/exp_days). Для быстрого прохода limit_rows ограничивает
количество прочитанных строк журнала.

Запуск: services\\.venv\\Scripts\\python.exe tests\\pipeline_smoke.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.adapters.journal import JournalStreamAdapter  # noqa: E402
from app import task_cfg  # noqa: E402
from app.research_bridge import module as _m  # noqa: E402
from app.services import feature_pipeline as fp  # noqa: E402
from app.services import inference as inf  # noqa: E402
from app.services import ml_registry  # noqa: E402

TASK = sys.argv[1] if len(sys.argv) > 1 else "wear"
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 500_000


def main() -> None:
    du = _m("data_utils")
    ref = du.load_ref_channels()
    union = set()
    for cfg in task_cfg.TASKS.values():
        union |= set(ref.loc[ref["тип_датчика"].isin(cfg["types"]),
                             "ид_канала_данных"])
    adapter = JournalStreamAdapter(year="2026", channels=union,
                                   extra_cols=task_cfg.extra_specs(ref))
    print("ингвест журнала (limit=%s)...")
    stat = adapter.ingest(limit_rows=LIMIT)
    print("ingest:", stat)

    print("сборка субъектов:", TASK)
    subjects = fp.build_subjects(TASK)
    print("subjects:", subjects.shape)
    cols = _m("tte_pipeline").subject_features(subjects)
    schema = ml_registry.get(TASK)["feature_cols"]
    print(f"X_cols={len(cols)} schema={len(schema)} match={cols == schema}")

    bucket = fp.latest_bucket(subjects)
    bsub = fp.subjects_for_bucket(subjects, bucket)
    print("бакет:", bucket, fp.bucket_to_dt(bucket), "субъектов на бакете:", len(bsub))
    if not len(bsub):
        print("нет субъектов на последнем бакете — ищем непустой")
        bsub = subjects.tail(2)
        bucket = int(bsub["бакет"].iloc[-1])
        bsub = fp.subjects_for_bucket(subjects, bucket)
        print("бакет:", bucket, "субъектов:", len(bsub))

    m = ml_registry.get(TASK)["model"]
    pr = _m("inference_contract").predict_risk(m, bsub)
    print(pr.describe().to_string())
    print("пример:\n", pr.head(3).to_string())

    rb = inf.rbam_frame(TASK, bsub)
    print("RBAM top:", rb.head(5).to_string())


if __name__ == "__main__":
    main()