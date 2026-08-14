"""MOTION research software for mobility, simulation, and prediction."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("motion")
except PackageNotFoundError:  # Source checkout without an installed distribution.
    __version__ = "0.1.0"

__all__ = ["__version__"]
