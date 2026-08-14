"""Application-level traceability for the seven MOTION macro use cases.

Import :mod:`motion.application.use_cases.catalog` to enumerate the
descriptors. Research-only packages expose traceability metadata only.
"""

from .descriptor import UseCaseDescriptor, UseCaseStatus

__all__ = ["UseCaseDescriptor", "UseCaseStatus"]
