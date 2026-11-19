"""Configuration sources and precedence (docs/27 §2).

Layer: Kernel (L1). This package is the only place allowed to read ``os.environ``
(docs/27 §6 rule 2). ``ROBOPROBE_CONFIG_FILE`` and ``ROBOPROBE_SECRETS_DIR`` locate the other
sources, so they are read from the process environment only (not from ``.env`` or TOML).
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic_settings import DotEnvSettingsSource, EnvSettingsSource

if TYPE_CHECKING:
    from pydantic_settings import BaseSettings

__all__ = [
    "CONFIG_FILE_ENV",
    "DEFAULT_CONFIG_FILE",
    "DEFAULT_SECRETS_DIR",
    "SECRETS_DIR_ENV",
    "SourceLayer",
    "collect_layers",
    "deep_merge",
    "flatten",
]

type Tree = dict[str, Any]

CONFIG_FILE_ENV = "ROBOPROBE_CONFIG_FILE"
DEFAULT_CONFIG_FILE = Path("roboprobe.toml")
SECRETS_DIR_ENV = "ROBOPROBE_SECRETS_DIR"
DEFAULT_SECRETS_DIR = Path("/run/secrets")

ENV_ALIASES: Mapping[str, tuple[str, ...]] = {
    "ROBOPROBE_DATABASE_URL": ("database", "url"),
    "ROBOPROBE_API_TOKEN": ("api", "token"),
}
"""Legacy/compose-friendly env names; the canonical ``ROBOPROBE_<A>__<B>`` form wins if both set."""


@dataclass(frozen=True, slots=True)
class _SecretFile:
    path: tuple[str, ...]
    pass_path: bool  # True: the setting is the file path; False: the setting is the content.


SECRET_FILES: Mapping[str, _SecretFile] = {
    "db_password": _SecretFile(("database", "password_file"), pass_path=True),
    "api_token": _SecretFile(("api", "token"), pass_path=False),
}
"""Recognised files in the secrets directory and the setting each one feeds."""


@dataclass(frozen=True, slots=True)
class SourceLayer:
    """One configuration source.

    Attributes:
        label: Name reported by ``explain_sources`` (``cli``, ``env``, ``toml:<path>``, ...).
        values: Nested values read from the source.
        strict: Whether unknown top-level keys are errors. False for env-style sources, which
            share a namespace with compose-level variables (docs/27 §4.12).
    """

    label: str
    values: Tree
    strict: bool


def collect_layers(
    settings_cls: type[BaseSettings],
    cli_overrides: Mapping[str, Any] | None,
    config_file: Path | None = None,
) -> list[SourceLayer]:
    """Read every source, highest precedence first.

    Order: CLI overrides > environment (incl. aliases) > ``.env`` > TOML file > secret files.

    Args:
        settings_cls: Root settings class whose ``model_config`` defines prefix and delimiter.
        cli_overrides: Nested mapping or dotted keys (``{"runner.max_budget": 50}``).
        config_file: Explicit TOML file (e.g. the CLI ``--config`` flag); wins over
            ``ROBOPROBE_CONFIG_FILE`` and ``./roboprobe.toml``.

    Returns:
        Source layers, highest precedence first; empty layers are kept for explainability.

    Raises:
        ValueError: If the explicit config file is missing or a TOML file cannot be parsed.
    """
    environ: Mapping[str, str] = os.environ
    toml_path = _toml_path(environ, config_file)
    secrets_dir = Path(environ.get(SECRETS_DIR_ENV) or DEFAULT_SECRETS_DIR)
    readers: list[tuple[str, bool, Callable[[], Tree]]] = [
        ("cli", True, lambda: expand_dotted(cli_overrides or {})),
        ("env", False, lambda: deep_merge(_aliases(environ), EnvSettingsSource(settings_cls)())),
        (".env", False, DotEnvSettingsSource(settings_cls)),
        (f"toml:{toml_path}", True, lambda: _read_toml(toml_path)),
        ("secrets", False, lambda: _read_secrets(secrets_dir)),
    ]
    return [SourceLayer(label, read(), strict) for label, strict, read in readers]


def expand_dotted(values: Mapping[str, Any]) -> Tree:
    """Turn ``{"a.b": 1, "c": {"d": 2}}`` into ``{"a": {"b": 1}, "c": {"d": 2}}``."""
    tree: Tree = {}
    for key, value in values.items():
        nested = expand_dotted(value) if isinstance(value, Mapping) else value
        tree = deep_merge(tree, _nest(tuple(key.split(".")), nested))
    return tree


def deep_merge(low: Mapping[str, Any], high: Mapping[str, Any]) -> Tree:
    """Recursively merge two trees; values in ``high`` win."""
    merged: Tree = dict(low)
    for key, value in high.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def flatten(tree: Mapping[str, Any], prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Yield ``(dotted.path, leaf)`` pairs of a nested mapping."""
    for key, value in tree.items():
        path = f"{prefix}{key}"
        if isinstance(value, Mapping) and value:
            yield from flatten(value, f"{path}.")
        else:
            yield path, value


def _nest(path: tuple[str, ...], value: Any) -> Tree:  # noqa: ANN401 - arbitrary config value
    tree: Tree = {path[-1]: value}
    for key in reversed(path[:-1]):
        tree = {key: tree}
    return tree


def _aliases(environ: Mapping[str, str]) -> Tree:
    tree: Tree = {}
    upper = {k.upper(): v for k, v in environ.items()}
    for name, path in ENV_ALIASES.items():
        if upper.get(name):
            tree = deep_merge(tree, _nest(path, upper[name]))
    return tree


def _toml_path(environ: Mapping[str, str], config_file: Path | None) -> Path | None:
    explicit = config_file or environ.get(CONFIG_FILE_ENV)
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            origin = "config file" if config_file else CONFIG_FILE_ENV
            msg = f"{origin} points to a missing file: {path}"
            raise ValueError(msg)
        return path
    return DEFAULT_CONFIG_FILE if DEFAULT_CONFIG_FILE.is_file() else None


def _read_toml(path: Path | None) -> Tree:
    if path is None:
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        msg = f"cannot parse TOML config file {path}: {exc}"
        raise ValueError(msg) from None


def _read_secrets(directory: Path) -> Tree:
    tree: Tree = {}
    if not directory.is_dir():
        return tree
    for name, spec in SECRET_FILES.items():
        file = directory / name
        if file.is_file():
            value: Any = file if spec.pass_path else file.read_text(encoding="utf-8").strip()
            tree = deep_merge(tree, _nest(spec.path, value))
    return tree
