import sys
import pathlib

_HERE = pathlib.Path.cwd()
if _HERE.name == "notebooks":
    RESEARCH = _HERE.parent
else:
    RESEARCH = _HERE
if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import data_utils as du
import features as fe

RECOMPUTE = False
print("dataset:", du.find_dataset_dir())