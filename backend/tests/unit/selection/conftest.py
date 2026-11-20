"""Silence Torch JIT deprecation raised at BoTorch/GPyTorch import (pytest warnings=error)."""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message=r".*torch\.jit\.script.*", category=FutureWarning)
