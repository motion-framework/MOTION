"""OR3 behavioral incident-risk prediction components.

This package is intentionally separate from the macro use cases UC-04, UC-06
and UC-07. Importing it performs no training, file I/O or simulator
connection.
"""

from .schema import (
    FEATURE_SCHEMA_VERSION,
    MODEL_FEATURES,
    TARGET_COLUMN,
    PredictionSchemaError,
    VehicleObservation,
)

__all__ = [
    "FEATURE_SCHEMA_VERSION",
    "MODEL_FEATURES",
    "TARGET_COLUMN",
    "PredictionSchemaError",
    "VehicleObservation",
]
