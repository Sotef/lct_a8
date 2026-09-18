%matplotlib inline
import sys
import pathlib

_HERE = pathlib.Path.cwd()
RESEARCH = _HERE.parent if _HERE.name == "notebooks" else _HERE
if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

import data_utils as du

DATASET = du.find_dataset_dir()
p_ty = DATASET / "value_by_type.csv"
p_ob = DATASET / "value_by_object.csv"

if not (p_ty.exists() and p_ob.exists()):
    raise SystemExit("Нет кэша value_by_*.csv — сначала: "
                     ".venv\\Scripts\\python.exe research/build_value_distribution.py")

VAL_TYPE = pd.read_csv(p_ty, dtype={"тип_датчика": str, "значение": str, "семантика": str})
VAL_OBJ = pd.read_csv(p_ob, dtype={"ид_объект": str, "значение": str, "семантика": str})
print("кэш готов:", VAL_TYPE.shape, "|", VAL_OBJ.shape, "| всего записей:",
      f"{VAL_TYPE['n'].sum():,}")

sns.set_theme(style="whitegrid")