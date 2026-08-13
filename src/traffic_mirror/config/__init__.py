"""Centralized static configuration and explicit runtime state."""

from .paths import ProjectPaths
from .settings import AppSettings, SettingsError, load_settings

__all__ = ["AppSettings", "ProjectPaths", "SettingsError", "load_settings"]
