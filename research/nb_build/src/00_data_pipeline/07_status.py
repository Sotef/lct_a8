# Стадия 6. Контроль артефактов
import pandas as pd

rows = []
for name in ["extracted/ext-journal-*.csv", "_buckets_raw/*.csv",
             "subdaily_panel_wear_6h.csv", "_obj_raw/*.csv",
             "daily_panel_object_context.csv"]:
    files = list(DATASET.glob(name))
    size_mb = sum(f.stat().st_size for f in files) / 1e6
    rows.append({"паттерн": name, "файлов": len(files), "суммарно, МБ": round(size_mb, 1)})
pd.DataFrame(rows)