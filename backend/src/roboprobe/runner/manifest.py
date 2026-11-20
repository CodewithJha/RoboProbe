"""Provenance manifest builder (docs/21 §4, ADR-0014).

``ManifestBuilder`` assembles the immutable ``manifest.json`` recorded for every run.
Git SHA and dirty flag come from build-time env / package metadata — never from shelling
out to ``git`` at runtime (containers may lack a checkout).

Layer: Application (L3).

Implements: T-043, FR-REP-002, PR-08
"""

from __future__ import annotations

import hashlib
import os
import platform
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from uuid import UUID

from roboprobe import __version__
from roboprobe.core.seeding import LOCALIZATION, PERCEPTION, SENSOR, SIMULATOR, derive_seed
from roboprobe.core.types import JsonValue
from roboprobe.scenario._documents import validate_document

__all__ = [
    "GIT_DIRTY_ENV",
    "GIT_SHA_ENV",
    "MANIFEST_SCHEMA_VERSION",
    "UNKNOWN_GIT_SHA",
    "ManifestBuilder",
    "hash_file_sha256",
    "hash_hostname",
    "hash_uv_lock",
    "resolve_git_metadata",
]

MANIFEST_SCHEMA_VERSION: Final = 1
"""Provenance schema version (docs/21 §4)."""

GIT_SHA_ENV: Final = "ROBOPROBE_GIT_SHA"
"""Build-arg / runtime env injecting the commit SHA (never shell out to git)."""

GIT_DIRTY_ENV: Final = "ROBOPROBE_GIT_DIRTY"
"""Optional ``true``/``false`` dirty flag injected at build time."""

UNKNOWN_GIT_SHA: Final = "unknown"
"""Placeholder when no build-time SHA was injected."""

_SHA256_PREFIX: Final = "sha256:"
_BYTES_PER_GIB: Final = 1024**3
_HOSTNAME_HASH_HEX: Final = 16


def hash_hostname(hostname: str) -> str:
    """Return a truncated SHA-256 of ``hostname`` (privacy when sharing bundles)."""
    return hashlib.sha256(hostname.encode("utf-8")).hexdigest()[:_HOSTNAME_HASH_HEX]


def hash_file_sha256(path: Path) -> str:
    """Hex SHA-256 of file contents at ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def hash_uv_lock(lock_path: Path | None = None) -> str:
    """SHA-256 of ``uv.lock``; empty string hex when the lock file is absent."""
    path = lock_path if lock_path is not None else _default_uv_lock()
    if path is None or not path.is_file():
        return hashlib.sha256(b"").hexdigest()
    return hash_file_sha256(path)


def resolve_git_metadata(
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[str, bool]:
    """Resolve ``(git_sha, dirty)`` from env / package metadata (no ``git`` subprocess)."""
    environ = os.environ if env is None else env
    sha = environ.get(GIT_SHA_ENV, "").strip() or UNKNOWN_GIT_SHA
    dirty_raw = environ.get(GIT_DIRTY_ENV, "").strip().lower()
    dirty = dirty_raw in {"1", "true", "yes"}
    return sha, dirty


def _default_uv_lock() -> Path | None:
    # backend/src/roboprobe/runner/manifest.py -> repo root or backend/
    here = Path(__file__).resolve()
    for candidate in (here.parents[4] / "backend" / "uv.lock", here.parents[3] / "uv.lock"):
        if candidate.is_file():
            return candidate
    return None


@dataclass
class ManifestBuilder:
    """Fluent builder for a provenance manifest (docs/21 §4).

    Call the ``with_*`` mutators then :meth:`build`. Relative path keys only in
    ``materialized``; hostnames are hashed.
    """

    _run_id: str | None = None
    _campaign_id: str | None = None
    _experiment_id: str | None = None
    _backend: dict[str, JsonValue] = field(default_factory=dict)
    _space_id: str | None = None
    _space_version: str | None = None
    _task_id: str | None = None
    _task_sha256: str | None = None
    _sut_id: str | None = None
    _sut_config_hash: str | None = None
    _scenario_hash: str | None = None
    _scenario_values: dict[str, JsonValue] = field(default_factory=dict)
    _run_seed: int | None = None
    _derived_seeds: dict[str, int] = field(default_factory=dict)
    _materialized: dict[str, str] = field(default_factory=dict)
    _config_snapshot: dict[str, JsonValue] = field(default_factory=dict)
    _hostname: str | None = None
    _cpu: str = ""
    _cores: int = 1
    _ram_gb: float = 0.0
    _wall_s: float = 0.0
    _sim_s: float = 0.0
    _rtf_mean: float | None = None
    _git_sha: str | None = None
    _dirty: bool | None = None
    _uv_lock_sha256: str | None = None
    _version: str = __version__

    def with_ids(
        self,
        *,
        run_id: UUID | str,
        campaign_id: UUID | str,
        experiment_id: UUID | str | None = None,
    ) -> ManifestBuilder:
        """Set run / campaign / optional experiment identifiers."""
        self._run_id = str(run_id)
        self._campaign_id = str(campaign_id)
        self._experiment_id = None if experiment_id is None else str(experiment_id)
        return self

    def with_backend(self, name: str, **details: JsonValue) -> ManifestBuilder:
        """Record backend name and optional version/image fields."""
        payload: dict[str, JsonValue] = {"name": name}
        payload.update(details)
        self._backend = payload
        return self

    def with_space(self, space_id: str, version: str) -> ManifestBuilder:
        """Record scenario-space identity."""
        self._space_id = space_id
        self._space_version = version
        return self

    def with_task(self, task_id: str, sha256: str) -> ManifestBuilder:
        """Record task id and content hash."""
        self._task_id = task_id
        self._task_sha256 = sha256
        return self

    def with_sut_profile(self, profile_id: str, config_hash: str) -> ManifestBuilder:
        """Record SUT profile id and config hash."""
        self._sut_id = profile_id
        self._sut_config_hash = config_hash
        return self

    def with_scenario(self, scenario_hash: str, values: Mapping[str, JsonValue]) -> ManifestBuilder:
        """Record scenario hash and parameter values."""
        self._scenario_hash = scenario_hash
        self._scenario_values = dict(values)
        return self

    def with_seeds(self, run_seed: int, *, derive: bool = True) -> ManifestBuilder:
        """Set the run seed and optionally derive sensor/perception/sim/localization streams."""
        self._run_seed = run_seed
        if derive:
            self._derived_seeds = {
                "sensor": derive_seed(run_seed, SENSOR),
                "perception": derive_seed(run_seed, PERCEPTION),
                "simulator": derive_seed(run_seed, SIMULATOR),
                "localization": derive_seed(run_seed, LOCALIZATION),
            }
        return self

    def with_materialized_files(
        self, files: Mapping[str, Path], *, workdir: Path | None = None
    ) -> ManifestBuilder:
        """Hash materialised files; keys are relative paths (never absolute)."""
        hashed: dict[str, str] = {}
        for key, path in files.items():
            rel = key
            if Path(key).is_absolute():
                base = workdir if workdir is not None else path.parent
                try:
                    rel = str(path.resolve().relative_to(base.resolve()))
                except ValueError:
                    rel = path.name
            hashed[rel.replace("\\", "/")] = f"{_SHA256_PREFIX}{hash_file_sha256(path)}"
        self._materialized = hashed
        return self

    def with_config_snapshot(self, snapshot: Mapping[str, JsonValue]) -> ManifestBuilder:
        """Store resolved oracle thresholds and backend settings (and any extra sections)."""
        self._config_snapshot = dict(snapshot)
        return self

    def with_host(
        self,
        *,
        hostname: str | None = None,
        cpu: str | None = None,
        cores: int | None = None,
        ram_gb: float | None = None,
    ) -> ManifestBuilder:
        """Capture host facts; hostname is hashed in :meth:`build`."""
        self._hostname = platform.node() if hostname is None else hostname
        self._cpu = platform.processor() or platform.machine() if cpu is None else cpu
        self._cores = os.cpu_count() or 1 if cores is None else cores
        if ram_gb is not None:
            self._ram_gb = ram_gb
        else:
            self._ram_gb = _detect_ram_gb()
        return self

    def with_timing(
        self, *, wall_s: float, sim_s: float, rtf_mean: float | None = None
    ) -> ManifestBuilder:
        """Record wall / sim duration and mean real-time factor."""
        self._wall_s = wall_s
        self._sim_s = sim_s
        if rtf_mean is not None:
            self._rtf_mean = rtf_mean
        elif wall_s > 0:
            self._rtf_mean = sim_s / wall_s
        else:
            self._rtf_mean = None
        return self

    def with_code(
        self,
        *,
        version: str | None = None,
        git_sha: str | None = None,
        dirty: bool | None = None,
        uv_lock_sha256: str | None = None,
    ) -> ManifestBuilder:
        """Override package / lock metadata (tests inject fixed values)."""
        if version is not None:
            self._version = version
        self._git_sha = git_sha
        self._dirty = dirty
        self._uv_lock_sha256 = uv_lock_sha256
        return self

    def build(self, *, validate: bool = True) -> dict[str, JsonValue]:
        """Assemble the manifest dict; optionally validate against the JSON schema.

        Raises:
            ValueError: If required fields were not set.
            roboprobe.core.errors.ValidationError: If schema validation fails.
        """
        missing = self._missing()
        if missing:
            msg = f"manifest incomplete: missing {', '.join(missing)}"
            raise ValueError(msg)
        git_sha, dirty = resolve_git_metadata()
        if self._git_sha is not None:
            git_sha = self._git_sha
        if self._dirty is not None:
            dirty = self._dirty
        uv_lock = self._uv_lock_sha256 if self._uv_lock_sha256 is not None else hash_uv_lock()
        hostname = self._hostname if self._hostname is not None else platform.node()
        seeds: dict[str, JsonValue] = {"run": int(self._run_seed)}  # type: ignore[arg-type]
        seeds.update({key: int(value) for key, value in self._derived_seeds.items()})
        config = dict(self._config_snapshot)
        if "oracles" not in config:
            config["oracles"] = {}
        manifest: dict[str, JsonValue] = {
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "run_id": self._run_id,
            "campaign_id": self._campaign_id,
            "experiment_id": self._experiment_id,
            "roboprobe": {
                "version": self._version,
                "git_sha": git_sha,
                "dirty": dirty,
                "uv_lock_sha256": uv_lock,
            },
            "backend": dict(self._backend),
            "space": {"id": self._space_id, "version": self._space_version},
            "task": {"id": self._task_id, "sha256": self._task_sha256},
            "sut_profile": {"id": self._sut_id, "config_hash": self._sut_config_hash},
            "scenario": {"hash": self._scenario_hash, "values": dict(self._scenario_values)},
            "seeds": seeds,
            "materialized": dict(self._materialized),
            "config_snapshot": config,
            "host": {
                "hostname_hash": hash_hostname(hostname),
                "cpu": self._cpu,
                "cores": self._cores,
                "ram_gb": self._ram_gb,
            },
            "timing": {
                "wall_s": self._wall_s,
                "sim_s": self._sim_s,
                "rtf_mean": self._rtf_mean,
            },
        }
        if validate:
            validate_document(manifest, schema="manifest", source="manifest.json")
        return manifest

    def _missing(self) -> list[str]:
        required = {
            "run_id": self._run_id,
            "campaign_id": self._campaign_id,
            "backend": self._backend.get("name"),
            "space_id": self._space_id,
            "space_version": self._space_version,
            "task_id": self._task_id,
            "task_sha256": self._task_sha256,
            "sut_id": self._sut_id,
            "sut_config_hash": self._sut_config_hash,
            "scenario_hash": self._scenario_hash,
            "run_seed": self._run_seed,
        }
        return [name for name, value in required.items() if value is None]


def _detect_ram_gb() -> float:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, ValueError, OSError):
        return 0.0
    if page_size <= 0 or pages <= 0:
        return 0.0
    return round((page_size * pages) / _BYTES_PER_GIB, 2)
