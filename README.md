# lct_a8 — Предиктивный ML-сервис аварий и отказов оборудования коллекторов

Веб-сервис прогнозирования отказов датчиков и аварий инженерных коллекторов АО «Москоллектор» (hackathon/технологическое соревнование). Стек: Python 3.12, FastAPI (бэкенд), PostgreSQL, LightGBM/CatBoost (ML), Jupyter (research).

## Структура репозитория

```
lct_a8/
├── research/            # ML Research Team: EDA, feature pipeline, модели, Jupyter
│   ├── .venv/           # venv Python 3.12 (ядро Jupyter: lct-a8-research)
│   ├── dataset/         # исходные .7z, распакованные CSV (extracted/), панели, справочники
│   ├── notebooks/       # 00_data_pipeline, 01..07 (данные/EDA), 08..11 (модели)
│   ├── nb_build/        # текстовые исходники ноутбуков (+ build.py)
│   ├── docs/            # DATA_REPORT.md, ML_PLAN.md, DATA_MATRIX.md, OPEN_QUESTIONS.md, PLAN_LAYER2_TTE.md
│   ├── models/          # обученные модели, предсказания холдаута, отчёты, графики
│   ├── archive_scripts/ # разовые скрипты EDA/диагностики (не используются на инференсе)
│   ├── data_utils.py    # чтение журналов, календарь кампаний
│   ├── features.py      # feature pipeline: панели, признаки, цели
│   ├── tte_pipeline.py  # survival-пайплайн слоя 2 («дней до события»)
│   ├── tte_experiments.py  # обучение/оценка TTE (discrete hazard + бенчмарки)
│   └── requirements.txt
└── services/            # Backend & Web Service Team: FastAPI-сервис
    ├── .venv/           # venv Python 3.12
    ├── requirements.txt
    └── SERVICE_PLAN.md  # план сервиса (уточнён по итогам встречи с экспертами)
```

## Окружение

Два изолированных venv на Python 3.12:

```powershell
# research — анализ данных и ML
D:\python312\python.exe -m venv research\.venv
research\.venv\Scripts\python.exe -m pip install -r research\requirements.txt
research\.venv\Scripts\python.exe -m ipykernel install --user --name lct-a8-research --display-name "Python 3.12 (research)"

# services — бэкенд
D:\python312\python.exe -m venv services\.venv
services\.venv\Scripts\python.exe -m pip install -r services\requirements.txt
```

Запуск Jupyter с ядром research:

```powershell
research\.venv\Scripts\python.exe -m jupyter lab
```

## Данные

- Исходные архивы: `research/dataset/ext-journal-{2019..2026}.7z` (внутри каждого — 1 CSV, схема идентична).
- Распакованные: `research/dataset/extracted/ext-journal-{год}.csv` (~15.9 ГБ суммарно).
- Справочники: `справочник_каналов_датчиков.csv`, `справочник_объектов_диспетчер.csv`, `журнал_событий_пример.csv`.
- Полное описание данных и EDA — в `research/docs/DATA_REPORT.md`.

## Кампании проверок (важно для модели)

Периоды массовых проверок/ремонтов (например, пик 2021W17–W22 после вступления
в силу ППР №1479 и СП 484/485/486 МЧС) **не являются реальными авариями** —
шумы от них нужно исключать из сплитов. Календарь реализован в
`research/data_utils.py` (`CAMPAIGN_WEEKS`, `EXCLUDE_WEEKS_DEFAULT`,
`filter_clean_weeks`). Подробности — в `research/docs/DATA_REPORT.md` → раздел 13.

## Документы ML-команды

- `research/docs/ML_PLAN.md` — план ML (раздел 0 — итоги встречи с экспертами 16.09).
- `research/docs/DATA_MATRIX.md` — матрица «задача → данные → связи (joins)».
- `research/docs/OPEN_QUESTIONS.md` — вопросы организаторам и ответы экспертов.
- `research/docs/DATA_REPORT.md` — отчёт по данным (EDA, недельный анализ, кампании).
- `research/docs/PLAN_LAYER2_TTE.md` — план/статус улучшения прогноза «через сколько дней» (слой 2, ноутбук 11).
- `research/docs/REPRODUCE_DATASETS.md` — как из `.7z` пересобрать все датасеты (`rebuild_all_datasets.py`).

## Текущий статус

- [x] Окружение: два venv Python 3.12, ядро Jupyter
- [x] Распаковка всех `.7z`
- [x] EDA: объёмы, схема, тревоги по типам, словарь статусов, структура тегов
- [x] EDA в Jupyter: ноутбуки `research/notebooks/01..06` + исходники `nb_build/src`
- [x] Подготовка данных: пайплайн `00_data_pipeline` + ноутбук `07_data_prep` (панели, нейтрализация кампаний)
- [x] Календарь кампаний проверок (`data_utils.CAMPAIGN_WEEKS`)
- [x] Feature pipeline: `features.py` (признаки каналов/объектов, горизонты 6–48ч)
- [x] Basline и горизонты: ноутбуки `08_wear_baseline`, `09_wear_horizons`, `10_wear_series` (событие = старт серии)
- [x] Слой 2 «через сколько дней»: survival-апгрейд `11_wear_tte` (discrete hazard, цензура, holdout 2025H2+2026)
- [ ] FastAPI-сервис, БД, frontend (дашборд рисков)