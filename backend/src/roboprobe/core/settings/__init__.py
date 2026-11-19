"""Typed, layered service settings: the single home of every tunable (docs/27, ADR-0015).

Layer: Kernel (L1). Domain packages import their *defaults* models (``OracleThresholds``,
``SelectionDefaults``, ...) from here; only this package reads the process environment.

Sources, highest precedence first (docs/27 §2): CLI overrides, ``ROBOPROBE_*`` environment
variables (``__`` nests), ``.env``, the TOML file (``ROBOPROBE_CONFIG_FILE`` or
``./roboprobe.toml``), secret files in ``ROBOPROBE_SECRETS_DIR`` (default ``/run/secrets``), and
the defaults declared on the models.

Implements: ADR-0015, docs/27 §2-§4.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Self

import pydantic
from pydantic import Field, PrivateAttr, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from roboprobe.core.errors import ConfigError
from roboprobe.core.settings._sources import ENV_ALIASES, collect_layers, deep_merge, flatten
from roboprobe.core.settings.analysis import AnalysisSettings, RiskSettings
from roboprobe.core.settings.api import ApiSettings
from roboprobe.core.settings.backends import BackendsSettings
from roboprobe.core.settings.database import DatabaseSettings
from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.core.settings.observability import LoggingSettings, ObservabilitySettings
from roboprobe.core.settings.oracles import OracleThresholds
from roboprobe.core.settings.runner import RunnerSettings
from roboprobe.core.settings.scenario import ScenarioSettings
from roboprobe.core.settings.selection import SelectionDefaults
from roboprobe.core.settings.storage import StorageSettings
from roboprobe.core.settings.worker import WorkerSettings
from roboprobe.core.types import JsonValue

__all__ = [
    "DEFAULT_SOURCE",
    "ENV_ALIASES",
    "AnalysisSettings",
    "ApiSettings",
    "BackendsSettings",
    "DatabaseSettings",
    "Environment",
    "ExperimentSettings",
    "LoggingSettings",
    "ObservabilitySettings",
    "OracleThresholds",
    "RiskSettings",
    "RoboProbeSettings",
    "RunnerSettings",
    "ScenarioSettings",
    "SelectionDefaults",
    "StorageSettings",
    "WorkerSettings",
    "explain_sources",
    "flatten",
    "load_settings",
]

Environment = Literal["local", "ci", "lab", "prod"]
DEFAULT_SOURCE = "default"
"""Label :func:`explain_sources` uses for values nobody overrode."""


class RoboProbeSettings(BaseSettings):
    """Root of the settings tree (docs/27 §3).

    Construct it with :func:`load_settings`. Direct construction only applies keyword
    arguments on top of the defaults (no environment or files), which keeps tests hermetic.
    """

    model_config = SettingsConfigDict(
        env_prefix="ROBOPROBE_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        # Unknown *root* keys are ignored so `.env` can also hold compose-level variables
        # (docs/27 §4.12); every section rejects unknown keys.
        extra="ignore",
        frozen=True,
        validate_default=True,
    )

    env: Environment = Field(default="local", description="Deployment environment.")
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    runner: RunnerSettings = Field(default_factory=RunnerSettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)
    backends: BackendsSettings = Field(default_factory=BackendsSettings)
    scenario: ScenarioSettings = Field(default_factory=ScenarioSettings)
    selection: SelectionDefaults = Field(default_factory=SelectionDefaults)
    oracles: OracleThresholds = Field(default_factory=OracleThresholds)
    analysis: AnalysisSettings = Field(default_factory=AnalysisSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    experiments: ExperimentSettings = Field(default_factory=ExperimentSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    _sources: dict[str, str] = PrivateAttr(default_factory=dict)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Use keyword arguments only; :func:`load_settings` resolves the real sources."""
        del settings_cls, env_settings, dotenv_settings, file_secret_settings
        return (init_settings,)

    @model_validator(mode="after")
    def _check_cross_section(self) -> Self:
        if self.worker.heartbeat_interval_s >= self.runner.heartbeat_timeout_s:
            msg = "worker.heartbeat_interval_s must be below runner.heartbeat_timeout_s"
            raise ValueError(msg)
        return self


def load_settings(
    cli_overrides: Mapping[str, Any] | None = None, *, config_file: Path | None = None
) -> RoboProbeSettings:
    """Resolve settings from every source and validate them (fail fast).

    Args:
        cli_overrides: Highest-precedence values, nested or dotted (``{"worker.concurrency": 4}``).
        config_file: Explicit TOML file (CLI ``--config``); overrides ``ROBOPROBE_CONFIG_FILE``.

    Returns:
        The validated, immutable settings tree; :func:`explain_sources` reports provenance.

    Raises:
        ConfigError: With every validation problem in ``context["errors"]`` (no input values,
            so secrets are never echoed).
    """
    try:
        layers = collect_layers(RoboProbeSettings, cli_overrides, config_file)
    except ValueError as exc:
        raise ConfigError(str(exc)) from None
    known = RoboProbeSettings.model_fields.keys()
    errors: list[JsonValue] = [
        {"loc": key, "msg": f"unknown setting (from {layer.label})", "type": "extra_forbidden"}
        for layer in layers
        if layer.strict
        for key in sorted(layer.values.keys() - known)
    ]
    merged: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    for layer in reversed(layers):  # lowest precedence first; higher layers overwrite
        merged = deep_merge(merged, layer.values)
        provenance.update(dict.fromkeys((path for path, _ in flatten(layer.values)), layer.label))
    try:
        settings = RoboProbeSettings(**{k: v for k, v in merged.items() if k in known})
    except pydantic.ValidationError as exc:
        errors += [
            {"loc": ".".join(map(str, err["loc"])), "msg": err["msg"], "type": err["type"]}
            for err in exc.errors(include_input=False, include_url=False)
        ]
    if errors:
        msg = f"invalid configuration: {len(errors)} error(s)"
        raise ConfigError(msg, context={"errors": errors})
    settings._sources = provenance
    return settings


def explain_sources(settings: RoboProbeSettings) -> dict[str, str]:
    """Return which source set each leaf value (``"default"`` when nobody overrode it).

    Args:
        settings: Settings returned by :func:`load_settings`.

    Returns:
        Mapping of dotted key (``"oracles.loc.e_max"``) to source label (``cli``, ``env``,
        ``.env``, ``toml:<path>``, ``secrets`` or ``default``).
    """
    explained = {path: DEFAULT_SOURCE for path, _ in flatten(settings.model_dump(by_alias=True))}
    # Paths that are not leaves (e.g. ignored compose-level variables) are not reported.
    explained.update({p: label for p, label in settings._sources.items() if p in explained})
    return explained
