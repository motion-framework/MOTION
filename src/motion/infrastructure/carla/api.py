"""Lazy access to the optional CARLA Python API."""

from __future__ import annotations

import importlib
from types import ModuleType


class CarlaUnavailableError(RuntimeError):
    pass


def load_carla_module() -> ModuleType:
    try:
        return importlib.import_module("carla")
    except ModuleNotFoundError as error:
        if error.name != "carla":
            raise
        raise CarlaUnavailableError(
            "The CARLA Python API is not installed. Install the wheel matching "
            "the configured CARLA release before starting a simulator session."
        ) from error
