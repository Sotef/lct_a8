import sys
import pathlib

_HERE = pathlib.Path.cwd()
RESEARCH = _HERE.parent if _HERE.name == "notebooks" else _HERE
if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))

import data_utils as du
import features as fe

DATASET = du.find_dataset_dir()
print("dataset:", DATASET)

# True — выполнять тяжёлые шаги сборки; False — только смотреть артефакты
REBUILD = False
print("REBUILD =", REBUILD)