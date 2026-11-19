import ast
import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import structlog

from roboprobe.core.logging import (
    CONTEXT_KEYS,
    EVENTS,
    REDACTED,
    bind_context,
    configure_logging,
    redact_secrets,
)
from roboprobe.core.settings import LoggingSettings

pytestmark = pytest.mark.unit

SRC = Path(__file__).resolve().parents[3] / "src"
LOG_METHODS = frozenset({"debug", "info", "warning", "error", "critical", "exception", "msg"})
FAKE_TOKEN = "dummy-token-value"


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def _configure(**settings: Any) -> io.StringIO:
    stream = io.StringIO()
    configure_logging(LoggingSettings(**settings), "roboprobe-test", "1.2.3", stream=stream)
    return stream


def _lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_json_line_schema_and_bound_ids() -> None:
    stream = _configure()
    with bind_context(campaign_id="c-1", run_id="r-1", worker_id="w-1", trace_id="t-1"):
        structlog.get_logger("roboprobe.runner").info("run.started", backend="kinematic2d")
    (line,) = _lines(stream)
    assert line["event"] == "run.started"
    assert line["level"] == "info"
    assert line["logger"] == "roboprobe.runner"
    assert line["service"] == "roboprobe-test"
    assert line["version"] == "1.2.3"
    assert line["ts"].endswith("Z")
    assert line["backend"] == "kinematic2d"
    assert {line[k] for k in ("campaign_id", "run_id", "worker_id", "trace_id")} == {
        "c-1",
        "r-1",
        "w-1",
        "t-1",
    }


def test_context_is_restored_after_block() -> None:
    stream = _configure()
    log = structlog.get_logger("roboprobe.x")
    with bind_context(run_id="outer"):
        with bind_context(run_id="inner", campaign_id=None):
            log.info("run.claimed")
        log.info("run.finished")
    log.info("run.requeued")
    inner, outer, after = _lines(stream)
    assert inner["run_id"] == "inner"
    assert "campaign_id" not in inner
    assert outer["run_id"] == "outer"
    assert "run_id" not in after


def test_bind_context_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unknown log context keys"), bind_context(user="x"):
        pass  # pragma: no cover - never entered


def test_context_keys_cover_docs() -> None:
    assert {"campaign_id", "run_id", "worker_id", "experiment_id", "trace_id"} == CONTEXT_KEYS


def test_secrets_are_redacted_in_output() -> None:
    stream = _configure()
    structlog.get_logger("roboprobe.api").info(
        "api.request",
        api_token=FAKE_TOKEN,
        headers={"Authorization": f"Bearer {FAKE_TOKEN}", "accept": "json"},
        database_dsn="postgresql://u:pw@h/db",
        db_password="pw",
        status=200,
    )
    raw = stream.getvalue()
    assert FAKE_TOKEN not in raw
    assert "pw@" not in raw
    (line,) = _lines(stream)
    assert line["api_token"] == line["database_dsn"] == line["db_password"] == REDACTED
    assert line["headers"] == {"Authorization": REDACTED, "accept": "json"}
    assert line["status"] == 200


def test_redaction_processor_recurses_into_containers() -> None:
    event = redact_secrets(
        None,
        "info",
        {"event": "x", "secret_key": "s", "n": 1, "items": [{"token": "t"}, ("a", {"dsn": "d"})]},
    )
    assert event == {
        "event": "x",
        "secret_key": REDACTED,
        "n": 1,
        "items": [{"token": REDACTED}, ("a", {"dsn": REDACTED})],
    }


def test_tracebacks_never_include_locals() -> None:
    stream = _configure()
    secret_local = FAKE_TOKEN  # noqa: F841 - must not leak through the traceback
    try:
        raise RuntimeError("boom")  # noqa: TRY301
    except RuntimeError:
        structlog.get_logger("roboprobe.x").exception("episode.launch_failed")
    raw = stream.getvalue()
    assert FAKE_TOKEN not in raw
    (line,) = _lines(stream)
    assert line["exception"][0]["exc_type"] == "RuntimeError"


def test_level_filtering() -> None:
    stream = _configure(level="WARNING")
    log = structlog.get_logger("roboprobe.x")
    log.info("run.started")
    log.warning("run.requeued", attempt=2)
    assert [line["event"] for line in _lines(stream)] == ["run.requeued"]


def test_include_caller_adds_callsite() -> None:
    stream = _configure(include_caller=True)
    structlog.get_logger("roboprobe.x").info("run.started")
    (line,) = _lines(stream)
    assert line["func_name"] == "test_include_caller_adds_callsite"
    assert {"module", "lineno"} <= line.keys()


def test_console_format_is_human_readable() -> None:
    stream = _configure(format="console")
    structlog.get_logger("roboprobe.x").info("run.started", api_token=FAKE_TOKEN)
    out = stream.getvalue()
    assert "run.started" in out
    assert FAKE_TOKEN not in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_defaults_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(LoggingSettings(), "roboprobe-test", "1.2.3")
    structlog.get_logger().info("config.loaded", sources=["default"])
    line = json.loads(capsys.readouterr().out)
    assert line["logger"] == "roboprobe-test"


def test_capture_logs_sees_events() -> None:
    _configure()
    with structlog.testing.capture_logs() as logs:
        structlog.get_logger("roboprobe.x").info("analysis.finished", n_runs=3)
    assert logs == [{"event": "analysis.finished", "n_runs": 3, "log_level": "info"}]


def _logged_events(tree: ast.AST) -> Iterator[ast.expr]:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LOG_METHODS
            and isinstance(node.func.value, ast.Name)
            and "log" in node.func.value.id.lower()
            and node.args
        ):
            yield node.args[0]


def test_every_logged_event_is_in_the_catalogue() -> None:
    unknown: list[str] = []
    for path in SRC.rglob("*.py"):
        for arg in _logged_events(ast.parse(path.read_text(encoding="utf-8"))):
            where = f"{path.relative_to(SRC)}:{arg.lineno}"
            if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
                unknown.append(f"{where} (event name must be a string literal)")
            elif arg.value not in EVENTS:
                unknown.append(f"{where} {arg.value!r}")
    assert not unknown, f"events missing from roboprobe.core.logging.EVENTS: {unknown}"


def test_catalogue_names_are_dotted_and_lowercase() -> None:
    assert all(name == name.lower() and "." in name for name in EVENTS)


def test_ast_scan_detects_violations() -> None:
    sample = ast.parse('log.info("nope.event")\nlogger.warning(f"x{y}")\nfoo.info("ignored")')
    args = list(_logged_events(sample))
    assert len(args) == 2
