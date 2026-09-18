# 11 · «Через сколько дней до события»: survival-апгрейд слоя 2 (TTE)

**Цель** — заменить ординальный слой 2 (`10_wear_series`) на корректную
survival-модель: правую цензуру, кривую выживаемости S(t), честные метрики.

- Событие = **старт серии** неисправностей (`features.add_series_targets`).
- Главная модель: **person-time discrete hazard** (CatBoost, шаг = 6 ч).
- Якоря/бенчмарки: Kaplan-Meier / Nelson-Aalen по типам каналов, CatBoost
  `SurvivalAft`, Random Survival Forest.
- Код: `research/tte_pipeline.py` (пайплайн) и `research/tte_experiments.py` (эксперименты).