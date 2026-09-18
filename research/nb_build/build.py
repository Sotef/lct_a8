# -*- coding: utf-8 -*-
# Сборка ноутбуков EDA из текстовых исходников.
#
# Структура:
#   nb_build/src/<notebook_name>/NN_<cell_name>.md  -> markdown ячейка
#   nb_build/src/<notebook_name>/NN_<cell_name>.py  -> code ячейка
#
# Запуск: research\\.venv\\Scripts\\python.exe research/nb_build/build.py
from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
SRC_DIR = HERE / "src"
OUT_DIR = HERE.parent / "notebooks"
OUT_DIR.mkdir(exist_ok=True)

KERNEL = {
    "kernelspec": {
        "display_name": "Python 3.12 (research)",
        "language": "python",
        "name": "lct-a8-research",
    },
    "language_info": {"name": "python", "version": "3.12.5"},
}


def read_cells(nb_dir: pathlib.Path) -> list[dict]:
    cells = []
    files = sorted(nb_dir.iterdir(), key=lambda p: p.name)  # по имени ячейки (числовой префикс)
    for fp in files:
        if fp.suffix == ".md":
            cells.append({"cell_type": "markdown", "metadata": {}, "source": fp.read_text(encoding="utf-8").splitlines(keepends=True)})
        elif fp.suffix == ".py":
            cells.append({
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": fp.read_text(encoding="utf-8").splitlines(keepends=True),
            })
    return cells


def main() -> None:
    for nb_dir in sorted(SRC_DIR.iterdir()):
        if not nb_dir.is_dir():
            continue
        nb = {
            "cells": read_cells(nb_dir),
            "metadata": KERNEL,
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        out = OUT_DIR / f"{nb_dir.name}.ipynb"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(nb, f, ensure_ascii=False, indent=1)
        print("OK ", out.name, "| cells:", len(nb["cells"]))


if __name__ == "__main__":
    main()