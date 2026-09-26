# -*- coding: utf-8 -*-
"""Мост к research-библиотекам (features / tte_pipeline / inference_contract).

ML-логика инкапсулирована в `research`; эндпоинты её не содержат (§1 BACKEND_SPEC).
Здесь только подмешиваем path и даём ленивые импорты.
"""
from __future__ import annotations

import importlib
import pathlib
import sys

from . import config

_RESEARCH_INSERTED = False


def research_path() -> pathlib.Path:
    return config.RESEARCH_DIR


def ensure_research_importable() -> None:
    global _RESEARCH_INSERTED
    if _RESEARCH_INSERTED:
        return
    rp = str(config.RESEARCH_DIR.resolve())
    if rp not in sys.path:
        sys.path.insert(0, rp)
    _RESEARCH_INSERTED = True


_get = {}


def module(name: str):
    """Ленивый импорт research-модуля (features, tte_pipeline, inference_contract, data_utils)."""
    ensure_research_importable()
    if name not in _get:
        _get[name] = importlib.import_module(name)
    return _get[name]