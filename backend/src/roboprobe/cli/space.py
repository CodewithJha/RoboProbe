"""``roboprobe space``: validate, register, list and upgrade scenario spaces.

Store adapters are loaded via ``importlib`` so this module stays import-linter clean
(bootstrap wiring, T-046).

Layer: Interface (L4).

Implements: T-045a, FR-CLI-001, FR-SCN-001
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Annotated, Protocol, cast

import typer
import yaml

from roboprobe.cli._context import get_state
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import JsonValue
from roboprobe.scenario._documents import load_yaml_document, read_document
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["app", "register_space", "uow_factory_from_settings"]


class _SpaceRow(Protocol):
    id: str
    version: str
    name: str


class _SpacePage(Protocol):
    items: list[_SpaceRow]


class _SpaceRepo(Protocol):
    def get(self, space_id: str, version: str) -> _SpaceRow | None: ...

    def add(self, record: object) -> None: ...

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> _SpacePage: ...


class _Uow(Protocol):
    spaces: _SpaceRepo

    def __enter__(self) -> _Uow: ...

    def __exit__(self, *args: object) -> None: ...

    def commit(self) -> None: ...


app = typer.Typer(
    name="space",
    help="Scenario space validate / register / list.",
    no_args_is_help=True,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
"""Repository root (``cli/space.py`` → … → ``backend`` → repo)."""


def _engine_mod() -> ModuleType:
    return importlib.import_module("roboprobe.store.engine")


def _uow_mod() -> ModuleType:
    return importlib.import_module("roboprobe.store.uow")


def _records_mod() -> ModuleType:
    return importlib.import_module("roboprobe.store.records")


@contextmanager
def uow_factory_from_settings(settings: RoboProbeSettings) -> Iterator[Callable[[], _Uow]]:
    """Yield a UoW factory; dispose the engine when the context exits."""
    engine_mod = _engine_mod()
    engine = engine_mod.create_engine_from_settings(settings.database)
    factory = engine_mod.session_factory(engine)
    uow_cls = _uow_mod().SqlAlchemyUnitOfWork
    channel = settings.database.notify_channel

    def _factory() -> _Uow:
        return cast("_Uow", uow_cls(factory, notify_channel=channel))

    try:
        yield _factory
    finally:
        engine.dispose()


def register_space(
    path: Path,
    settings: RoboProbeSettings,
    *,
    base_dir: Path | None = None,
) -> _SpaceRow:
    """Validate ``path`` and persist the space definition + version."""
    root = REPO_ROOT if base_dir is None else base_dir
    space = ScenarioSpace.from_yaml(path, base_dir=root)
    document = load_yaml_document(read_document(path), source=str(path))
    if not isinstance(document, dict):
        msg = "space document must be a mapping"
        raise ValidationError(msg, context={"path": str(path)})
    definition = {str(key): _as_json(value) for key, value in document.items()}
    record = _records_mod().SpaceRecord(
        id=space.id,
        version=space.version,
        name=space.name,
        definition=definition,
        schema_version=int(document.get("schema_version", 1)),
    )
    with uow_factory_from_settings(settings) as make_uow, make_uow() as uow:
        existing = uow.spaces.get(record.id, record.version)
        if existing is None:
            uow.spaces.add(record)
        uow.commit()
    return cast("_SpaceRow", record)


def _as_json(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list):
        return [_as_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _as_json(item) for key, item in value.items()}
    return str(value)


@app.command("validate")
def validate_cmd(
    ctx: typer.Context,
    yaml_path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="Space YAML file."),
    ],
) -> None:
    """Validate a scenario space file (exit 0 / 2 with path-to-error messages)."""
    state = get_state(ctx)
    state.bootstrap()
    space = ScenarioSpace.from_yaml(yaml_path, base_dir=REPO_ROOT)
    state.output.data({"id": space.id, "version": space.version, "name": space.name})


@app.command("register")
def register_cmd(
    ctx: typer.Context,
    yaml_path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="Space YAML file."),
    ],
) -> None:
    """Validate and store a space definition + version in the database."""
    state = get_state(ctx)
    settings = state.bootstrap()
    record = register_space(yaml_path, settings, base_dir=REPO_ROOT)
    state.output.data({"id": record.id, "version": record.version, "name": record.name})


@app.command("list")
def list_cmd(ctx: typer.Context) -> None:
    """List registered scenario spaces."""
    state = get_state(ctx)
    settings = state.bootstrap()
    with uow_factory_from_settings(settings) as make_uow, make_uow() as uow:
        page = uow.spaces.list()
        rows = [[item.id, item.version, item.name] for item in page.items]
    state.output.table(["id", "version", "name"], rows, title="Scenario spaces")


@app.command("upgrade")
def upgrade_cmd(
    ctx: typer.Context,
    yaml_path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="Space YAML file."),
    ],
) -> None:
    """Migrate a space file to the current ``schema_version`` (stub until schema v2).

    Docs/05 §11 and docs/33: future schema versions will rewrite the YAML in place.
    """
    state = get_state(ctx)
    state.bootstrap()
    document = load_yaml_document(read_document(yaml_path), source=str(yaml_path))
    if not isinstance(document, dict):
        msg = "space document must be a mapping"
        raise ValidationError(msg, context={"path": str(yaml_path)})
    version = document.get("schema_version")
    if version != 1:
        msg = (
            f"space upgrade cannot migrate schema_version={version!r}; "
            "only schema_version=1 is supported (no rewrite needed)"
        )
        raise NotFoundError(msg, context={"path": str(yaml_path), "schema_version": version})
    # schema_version 1 is current: write-through (identity) so the command is usable in scripts.
    yaml_path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    state.output.data({"path": str(yaml_path), "schema_version": 1, "upgraded": False})
