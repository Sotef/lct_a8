import sys
import pathlib

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

# True — полный пересчёт из сырых CSV (медленно, ~10-15 мин).
# False — читать готовый артефакт weekly_summary.csv (быстро).
RECOMPUTE = False

print("dataset:", du.find_dataset_dir())