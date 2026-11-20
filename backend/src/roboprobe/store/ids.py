"""UUIDv7 identifiers generated in Python (docs/11 §1).

Layer: Adapter (infrastructure).
"""

from __future__ import annotations

from uuid import UUID

import uuid_utils

__all__ = ["new_uuid"]


def new_uuid() -> UUID:
    """Return a time-ordered UUIDv7 as :class:`uuid.UUID`."""
    return UUID(str(uuid_utils.uuid7()))
