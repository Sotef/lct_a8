# research/docs — индекс документации

Канонические документы (читай по необходимости, а не все подряд):

| Документ | О чём |
|---|---|
| `ML_PLAN.md` | Единый ML-документ: Часть I — архитектура/план; Часть II — статус fire/sensor/access/wear; Часть III — продуктовая рамка MVP |
| `BACKLOG.md` | Нереализованное/отложенное и блокеры данных |
| `OPEN_QUESTIONS.md` | Вопросы заказчику и ответы экспертов (реестр Q&A) |
| `DATA_REPORT.md` | EDA: объёмы, типы, словарь статусов, недельный анализ, кампании |
| `DATA_MATRIX.md` | Матрица «задача → данные → joins» |
| `RISK_PIVOT_REPORT.md` | Риск-портфель RBAM и план ТО (генерируется nb 30) |
| `TZ_COMPLIANCE_REPORT.md` | Соответствие «букве ТЗ» (генерируется `report_tz_compliance.py`) |
| `SEVERITY_MAP.md` | Веса последствий для RBAM-приоритета |
| `API_CONTRACT.md` | API-контракт ядра MVP для backend |
| `ADAPTERS_README.md` | Интерфейсы read-only адаптеров внешних данных (P2) |
| `REPRODUCE_DATASETS.md` | Как пересобрать датасеты из `.7z` |

Соседние: корень — `README.md` (обзор+запуск), `STATUS.md` (готовность/метрики/блокеры),
`ARCHITECTURE.md` (архитектура и использование); сервис — `services/README.md`,
`services/BACKEND_SPEC.md`, `services/SERVICE_PLAN.md`.
