# Как воспроизвести датасеты из `.7z` (репро)

Полная цепочка «`.7z` → все панели/субъекты/агрегаты» описана в
`research/rebuild_all_datasets.py`. Ниже — инструкция для нового окружения.

## 1. Необходимое

- Python 3.12 (напр. `D:\python312\python.exe`).
- Исходные архивы `ext-journal-{2019..2026}.7z` — положить в `research/dataset/`
  (около 1.6 ГБ суммарно).
- Справочники `справочник_каналов_датчиков.csv`, `справочник_объектов_диспетчер.csv`
  и `журнал_событий_пример.csv` — небольшие, можно коммитить в git.

## 2. Окружение

```powershell
cd lct_a8
D:\python312\python.exe -m venv research\.venv
research\.venv\Scripts\python.exe -m pip install -r research\requirements.txt
research\.venv\Scripts\python.exe -m ipykernel install --user --name lct-a8-research --display-name "Python 3.12 (research)"   # для Jupyter
```

## 3. Собрать все датасеты

```powershell
cd research
.\.venv\Scripts\python.exe rebuild_all_datasets.py --check     # статус (что уже есть)
.\.venv\Scripts\python.exe rebuild_all_datasets.py --all        # шаги 0..6 (~1 ч)
.\.venv\Scripts\python.exe rebuild_all_datasets.py --all --values   # + распределения значений (~8 мин)
```

Шаги (идемпотентны: уже готовые файлы пропускаются; `--force` пересчитает):

| # | Что создаётся | Ключевая функция |
|---|---|---|
| 0 | `dataset/extracted/ext-journal-{год}.csv` | py7zr |
| 1 | `dataset/_buckets_raw/_buckets_raw_{год}.csv` (6ч-агрегаты WEAR) | `features._aggregate_bucket_year` |
| 2 | `dataset/subdaily_panel_wear_6h.csv` | `features.make_subdaily_panel` |
| 3 | `daily_panel_Состояние_насоса_...csv` (суточный WEAR, ноутбук 08) | `features.make_daily_panel` |
| 4 | `dataset/daily_panel_object_context.csv` | `features.make_object_panel` |
| 5 | `dataset/subdaily_panel_{fire,sensor,access}6h.csv` | `task_tte.build_task_panel` |
| 6 | `dataset/tte_subjects*.parquet` (wear, fire, sensor, access) | `tte_experiments.build_dataset`, `task_tte.prepare_subjects` |
| 7 | `dataset/value_by_type.csv`, `value_by_object.csv` | `build_value_distribution.main` (только с `--values`) |

Итог — ~19 ГБ (из них 15.9 ГБ — распакованные журналы в `extracted/`).

## 4. Проверка

```powershell
.\.venv\Scripts\python.exe rebuild_all_datasets.py --check   # все пункты 8/8 + размеры
```
Открыть `notebooks/00_data_pipeline.ipynb` (REBUILD=False) — он покажет те же
артефакты. Затем можно запускать ноутбуки 01–13.

Примечания:
- `dataset/train_panel_дым.csv` и `dataset/daily_agg_дыма_*.csv` — артефакты
  ноутбука 07 (`make_daily_panel` для дыма/прототипа); в пайплайны 08–13
  не входят и регенерируются там же.
- Модели/предсказания (`research/models/`) генерируются ноутбуками/скриптами
  и в «датасеты» не входят.

## 5. Что коммитить в git

**Коммитить:** исходный код, `requirements.txt`, ноутбуки (`.ipynb`), справочники,
`docs/`, планы. **Не коммитить** (генерируется шагом выше, большие):
`dataset/extracted/`, `_buckets_raw/`, `_obj_raw/`, `subdaily_panel_*6h.csv`,
`daily_panel_*`, `tte_subjects*.parquet`, `value_by_*.csv`, а также `.venv/`.
Сами `.7z` — на выбор: либо отдельное хранилище/гит-LFS, либо раздавать вне git.
Пример `.gitignore` — в корне репозитория.