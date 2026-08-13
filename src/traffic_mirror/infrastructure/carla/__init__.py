"""CARLA infrastructure adapters.

Importing this package never imports the optional :mod:`carla` dependency and
never opens a simulator connection.  The dependency is resolved only when a
session is explicitly created.
"""

__all__: list[str] = []
