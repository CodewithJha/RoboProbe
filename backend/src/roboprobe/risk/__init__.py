"""Risk mapping of the operating envelope and failure-region volume estimates.

Layer: Domain (L2). See docs/16 §2 for the allowed import directions.
"""

from roboprobe.risk.mapper import (
    REGION_FAILURE,
    REGION_SAFE,
    REGION_UNCERTAIN,
    RiskMapper,
    RiskSlice,
    load_slices,
    save_slices,
)

__all__ = [
    "REGION_FAILURE",
    "REGION_SAFE",
    "REGION_UNCERTAIN",
    "RiskMapper",
    "RiskSlice",
    "load_slices",
    "save_slices",
]
