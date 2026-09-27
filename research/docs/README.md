# research/docs — индекс документации

Канонические документы (читай по необходимости, а не все подряд):

| Документ | О чём |
|---|---|
| `ML_PLAN.md` | Архитектура и план ML (в т.ч. §0 — итоги встречи с экспертами 16.09) |
| `PLAN_OTHER_TASKS.md` | fire/sensor/access + wear: хронология экспериментов и итоги P0/P1 |
| `MVP_PIVOT.md` | Ядро MVP (CBM/RBAM/RUL) + fallback «буква ТЗ» |
| `DATA_REPORT.md` | EDA: объёмы, типы, словарь статусов, недельный анализ, кампании |
| `DATA_MATRIX.md` | Матрица «задача → данные → joins» |
| `OPEN_QUESTIONS.md` | Вопросы заказчику и блокеры задач |
| `RISK_PIVOT_REPORT.md` | Риск-портфель RBAM и план ТО (генерируется nb 30) |
| `TZ_COMPLIANCE_REPORT.md` | Соответствие «букве ТЗ» (генерируется `report_tz_compliance.py`) |
| `SEVERITY_MAP.md` | Веса последствий для RBAM-приоритета |
| `API_CONTRACT.md` | API-контракт ядра MVP для backend |
| `ADAPTERS_README.md` | Интерфейсы read-only адаптеров внешних данных (P2) |
| `REPRODUCE_DATASETS.md` | Как пересобрать датасеты из `.7z` |
| `PLAN_LAYER2_TTE.md` | Слой 2 «через сколько дней» (survival, статус) |

Соседние: корень — `README.md` (обзор+запуск), `STATUS.md` (сводка готовности, метрики, блокеры);
сервис — `services/README.md`, `services/BACKEND_SPEC.md`, `services/SERVICE_PLAN.md`.
