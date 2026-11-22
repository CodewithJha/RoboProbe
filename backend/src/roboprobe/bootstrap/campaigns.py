"""Campaign backend capability wiring (T-081b, FR-API-001)."""

from __future__ import annotations

from roboprobe.backends.registry import get_backend
from roboprobe.core.errors import PluginError, ValidationError
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.scenario.repo_root import discover_repo_root

__all__ = ["campaign_supported_params"]


def campaign_supported_params(backend: str, settings: RoboProbeSettings) -> frozenset[str]:
    """Resolve a registered backend without importing adapters into application services."""
    root = discover_repo_root()
    k2d = settings.backends.kinematic2d
    gazebo = settings.backends.gazebo_nav2
    resolved = settings.model_copy(
        update={
            "backends": settings.backends.model_copy(
                update={
                    "kinematic2d": k2d.model_copy(update={"model_file": root / k2d.model_file}),
                    "gazebo_nav2": gazebo.model_copy(
                        update={"perception_model_file": root / gazebo.perception_model_file}
                    ),
                }
            )
        }
    )
    try:
        return frozenset(get_backend(backend, resolved).capabilities.supported_params)
    except PluginError as exc:
        raise ValidationError(str(exc)) from exc
