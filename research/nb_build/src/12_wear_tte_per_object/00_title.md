# 12 · TTE: модели по объектам vs глобальная модель

**Цель** — проверить, что выигрывает: одна глобальная discrete-hazard модель
и/или отдельная модель на **каждом объекте**. Модели обучаются так же, как в
`11_wear_tte` (person-time, цензура, holdout ≥ 2025-07-01), но локальная —
только на строках своего объекта.

- Обучение: `research/tte_per_object.py` (модели → `research/models/objects/`).
- Результаты: `models/per_object_results.csv` + `models/per_object_summary.json`.
- Метрики на holdout: Uno-C, meanAUC, IBS, PR-AUC(P(24ч)) — локальная и
  глобальная на **одних и тех же** holdout-субъектах объекта.