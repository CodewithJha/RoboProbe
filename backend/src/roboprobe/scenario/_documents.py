"""Strict loading of user-facing YAML documents and JSON Schema validation (docs/06 §5, TM-02).

Shared by the scenario-space, task, scenario and profile loaders. Guarantees:

* ``yaml.safe_load`` semantics only: language tags such as ``!!python/object`` are rejected.
* Duplicate mapping keys are rejected (PyYAML silently keeps the last one otherwise).
* Timestamps stay strings, exactly as JSON Schema sees them.
* Optional byte-size limit, so uploads cannot exhaust memory.
* Alias expansions are capped (``scenario.yaml_max_aliases``), so a billion-laughs document
  is rejected before it is expanded.
* Every problem is reported as ``{"path": <JSON pointer>, "message": ...}`` inside a
  :class:`~roboprobe.core.errors.ValidationError`.

Implements: FR-SCN-001
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema.exceptions
import yaml
from jsonschema import Draft202012Validator
from pydantic import JsonValue

from roboprobe.core import errors
from roboprobe.core.settings.scenario import ScenarioSettings

__all__ = [
    "document_error",
    "json_pointer",
    "load_yaml_document",
    "read_document",
    "schema_validator",
    "validate_document",
]

_SCHEMA_SUFFIX = ".schema.json"
_TIMESTAMP_TAG = "tag:yaml.org,2002:timestamp"
_ROOT_POINTER = ""


class _StrictSafeLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys and does not resolve timestamps."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        """Build a mapping, rejecting duplicate keys."""
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(  # noqa: TRY003 - PyYAML error type
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


_StrictSafeLoader.yaml_implicit_resolvers = {
    first: [(tag, regex) for tag, regex in resolvers if tag != _TIMESTAMP_TAG]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def default_yaml_max_aliases() -> int:
    """Return the configured cap on YAML alias expansions (TM-02)."""
    value = ScenarioSettings.model_fields["yaml_max_aliases"].default
    if not isinstance(value, int):
        msg = "yaml_max_aliases default must be an int"
        raise TypeError(msg)
    return value


def _alias_limiting_loader(max_aliases: int) -> type[yaml.SafeLoader]:
    """Safe loader that refuses documents expanding more than ``max_aliases`` aliases."""

    class Loader(_StrictSafeLoader):
        def __init__(self, stream: str | bytes) -> None:
            super().__init__(stream)
            self._alias_count = 0
            self._max_aliases = max_aliases

        def compose_node(self, parent: yaml.Node | None, index: int) -> yaml.Node | None:
            if self.check_event(yaml.AliasEvent):
                self._alias_count += 1
                if self._alias_count > self._max_aliases:
                    event = self.peek_event()  # type: ignore[no-untyped-call]
                    mark = getattr(event, "start_mark", None)
                    message = f"too many aliases (limit {self._max_aliases})"
                    raise yaml.composer.ComposerError(  # noqa: TRY003 - PyYAML requires the message
                        "while composing an alias",
                        mark,
                        message,
                        mark,
                    )
            return super().compose_node(parent, index)

    return Loader


def document_error(
    source: str,
    issues: list[tuple[str, str]],
    code: errors.ErrorCode = errors.ErrorCode.VALIDATION_ERROR,
) -> errors.ValidationError:
    """Build the error raised for an invalid document.

    Args:
        source: File name or ``"<upload>"``.
        issues: ``(json_pointer, message)`` pairs; ``""`` is the document root.
        code: Error code (e.g. ``SPACE_INVALID``).
    """
    summary = "; ".join(f"{path or '/'}: {message}" for path, message in issues)
    error_list: list[JsonValue] = [{"path": path, "message": message} for path, message in issues]
    context: dict[str, JsonValue] = {"source": source, "errors": error_list}
    return errors.ValidationError(f"{source} is invalid: {summary}", code=code, context=context)


def read_document(path: Path) -> bytes:
    """Read a document file.

    Raises:
        roboprobe.core.errors.NotFoundError: If ``path`` does not exist.
    """
    try:
        return path.read_bytes()
    except FileNotFoundError as exc:
        msg = f"file not found: {path}"
        raise errors.NotFoundError(msg, context={"path": str(path)}) from exc


def load_yaml_document(
    text: str | bytes,
    *,
    source: str,
    code: errors.ErrorCode = errors.ErrorCode.VALIDATION_ERROR,
    max_bytes: int | None = None,
    max_aliases: int | None = None,
) -> object:
    """Parse one YAML document strictly.

    Args:
        text: Document content.
        source: Name used in error messages (file name or ``"<upload>"``).
        code: Error code to raise with (e.g. ``SPACE_INVALID``).
        max_bytes: Reject documents larger than this many bytes (``None`` = unlimited).
        max_aliases: Alias-expansion cap. ``scenario.yaml_max_aliases`` when omitted.

    Returns:
        The parsed document (plain dicts, lists and scalars).

    Raises:
        roboprobe.core.errors.ValidationError: Oversized input, syntax errors, unsafe tags,
            duplicate keys, or too many aliases.
    """
    raw = text.encode("utf-8") if isinstance(text, str) else text
    if max_bytes is not None and len(raw) > max_bytes:
        message = f"document is {len(raw)} bytes; limit is {max_bytes}"
        raise document_error(source, [(_ROOT_POINTER, message)], code)
    alias_cap = default_yaml_max_aliases() if max_aliases is None else max_aliases
    try:
        document: object = yaml.load(raw, Loader=_alias_limiting_loader(alias_cap))  # noqa: S506
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        problem = getattr(exc, "problem", None) or str(exc)
        message = f"YAML error{where}: {problem}"
        raise document_error(source, [(_ROOT_POINTER, message)], code) from exc
    return document


def _schema_file(name: str) -> Path:
    """Locate ``schemas/<name>.schema.json`` in an installed wheel or a source checkout."""
    filename = f"{name}{_SCHEMA_SUFFIX}"
    packaged = Path(str(resources.files("roboprobe"))) / "schemas" / filename
    if packaged.is_file():
        return packaged
    # Source checkout: backend/src/roboprobe/scenario/_documents.py -> <repo>/schemas.
    return Path(__file__).resolve().parents[4] / "schemas" / filename


def json_pointer(path: Iterable[str | int]) -> str:
    """RFC 6901 pointer for a sequence of keys/indices (``""`` is the root)."""
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in path)


def _location(error: jsonschema.exceptions.ValidationError) -> list[str]:
    return [str(part) for part in error.absolute_path]


@cache
def schema_validator(name: str) -> Draft202012Validator:
    """Return a cached validator for the named schema (e.g. ``"task"``).

    Raises:
        FileNotFoundError: If the schema file does not exist.
    """
    schema = json.loads(_schema_file(name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate_document(
    document: object,
    *,
    schema: str,
    source: str,
    code: errors.ErrorCode = errors.ErrorCode.VALIDATION_ERROR,
) -> None:
    """Validate ``document`` against a schema in ``schemas/``.

    Raises:
        roboprobe.core.errors.ValidationError: Listing every violation with its JSON pointer,
            ordered by location.
    """
    found = sorted(schema_validator(schema).iter_errors(document), key=_location)
    if found:
        raise document_error(
            source, [(json_pointer(e.absolute_path), e.message) for e in found], code
        )
