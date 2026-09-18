import json
import pathlib

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

_HERE = pathlib.Path.cwd()
RESEARCH = _HERE.parent if _HERE.name == "notebooks" else _HERE

df = pd.read_csv(RESEARCH / "models" / "per_object_results.csv", dtype={"объект": str})
with open(RESEARCH / "models" / "per_object_summary.json", encoding="utf-8") as f:
    summ = json.load(f)

print("объектов:", len(df))
print("параметры:", {k: v for k, v in summ["params"].items()
                     if k in ("iters", "lr", "depth", "cap", "min_train")})