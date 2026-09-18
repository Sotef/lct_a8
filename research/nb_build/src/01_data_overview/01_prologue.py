import sys
import pathlib

# Подключение папки research/ к import-пути (data_utils.py)
_HERE = pathlib.Path.cwd()
if _HERE.name == "notebooks":
    RESEARCH = _HERE.parent
else:
    RESEARCH = _HERE
if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))

import pandas as pd
import numpy as np
import data_utils as du

# Если True — полный пересчёт из сырых CSV (медленно, минуты).
# Если False — читать готовые артефакты из dataset/ (быстро).
RECOMPUTE = True

print("dataset:", du.find_dataset_dir())
print("pandas:", pd.__version__)
print("numpy:", np.__version__)