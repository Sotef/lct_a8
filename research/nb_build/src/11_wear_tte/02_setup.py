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

import data_utils as du
import features as fe
import tte_pipeline as tte
import tte_experiments as ex
from tte_experiments import (baseline_survival_by_type, build_dataset,
                             calibration_oe, fit_benchmarks, fit_discrete_hazard,
                             pick_threshold, pr_at_horizon, predict_survival_discrete,
                             survival_metrics, verify_no_lookup)

pd.set_option("display.max_columns", 60)
pd.set_option("display.width", 170)

# Параметры эксперимента (уменьшите n_* и iters для быстрого прогона)
CFG = dict(
    n_starts=25_000, n_fault=18_000, n_nonfault=18_000,
    n_val=9_000, n_hold=30_000,
    iters=500, lr=0.05, depth=6, seed=42,
    bench=True,          # бенчмарки SurvivalAft / RSF (медленно)
)
print("dataset:", du.find_dataset_dir())
print("граница обучения:", tte.TRAIN_END.date(),
      "| граница холдаута:", tte.HOLDOUT_START.date())