"""Tests for Trace Parquet serialisation and validation (T-018; docs/11 §6.2, FR-RUN-004)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from tests.factories import make_trace

from roboprobe.backends import trace_io
from roboprobe.core import errors
from roboprobe.core.types import Trace

pytestmark = pytest.mark.unit

FR_MIN_HZ = 10.0
FR_MAX_GAP_S = 0.2
META = {"run_id": "r-1", "backend": "kinematic2d", "sample_hz": 20.0, "seed": 7, "tags": ["a"]}


def assert_traces_equal(a: Trace, b: Trace) -> None:
    for field in dataclasses.fields(Trace):
        left, right = getattr(a, field.name), getattr(b, field.name)
        if isinstance(left, np.ndarray):
            assert isinstance(right, np.ndarray)
            assert right.dtype == left.dtype, field.name
            np.testing.assert_array_equal(right, left, err_msg=field.name)
        else:
            assert right == left, field.name


@pytest.fixture
def trace() -> Trace:
    base = make_trace(n=50, dt=0.05, meta=META, goal=(2.5, -0.125))
    rng = np.random.default_rng(3)
    return dataclasses.replace(
        base,
        gt_yaw=rng.normal(size=50),
        contact=np.arange(50) % 7 == 0,
        rtf=rng.uniform(0.5, 1.5, size=50).astype(np.float32),
    )


def test_round_trip_is_identical(tmp_path: Path, trace: Trace) -> None:
    path = tmp_path / "trace.parquet"
    trace_io.write_trace(trace, path)
    assert_traces_equal(trace_io.read_trace(path), trace)


def test_round_trip_without_rtf(tmp_path: Path) -> None:
    trace = make_trace(n=5)
    path = tmp_path / "trace.parquet"
    trace_io.write_trace(trace, path)
    back = trace_io.read_trace(path)
    assert back.rtf is None
    assert_traces_equal(back, trace)


def test_empty_trace_round_trips(tmp_path: Path) -> None:
    trace = make_trace(n=0)
    path = tmp_path / "trace.parquet"
    trace_io.write_trace(trace, path)
    assert trace_io.read_trace(path).n_samples == 0


def test_file_schema_units_metadata_and_compression(tmp_path: Path, trace: Trace) -> None:
    path = tmp_path / "trace.parquet"
    trace_io.write_trace(trace, path)
    schema = pq.read_schema(path)
    assert schema.names == trace_io.TRACE_SCHEMA.names
    assert schema.field("t").metadata == {b"unit": b"s"}
    assert schema.field("cmd_w").metadata == {b"unit": b"rad/s"}
    assert schema.field("nav_status").type == pa.int8()
    assert schema.field("rtf").type == pa.float32()
    meta = {k.decode(): json.loads(v) for k, v in (schema.metadata or {}).items()}
    assert meta["trace_schema_version"] == 1
    assert (meta["goal_x"], meta["goal_y"]) == (2.5, -0.125)
    assert (meta["run_id"], meta["backend"], meta["sample_hz"]) == ("r-1", "kinematic2d", 20.0)
    assert meta["meta"] == META
    column = pq.ParquetFile(path).metadata.row_group(0).column(0)
    assert column.compression == "ZSTD"


def test_promoted_keys_are_optional(tmp_path: Path) -> None:
    path = tmp_path / "trace.parquet"
    trace_io.write_trace(make_trace(n=3), path)
    keys = set((pq.read_schema(path).metadata or {}).keys())
    assert keys == {b"trace_schema_version", b"goal_x", b"goal_y", b"meta"}


def rewrite(path: Path, table: pa.Table, **metadata: object) -> Path:
    raw = dict(table.schema.metadata or {})
    for key, value in metadata.items():
        if value is None:
            raw.pop(key.encode(), None)
        else:
            raw[key.encode()] = value if isinstance(value, bytes) else json.dumps(value).encode()
    out = path.with_name("edited.parquet")
    pq.write_table(table.replace_schema_metadata(raw), out)
    return out


@pytest.fixture
def written(tmp_path: Path, trace: Trace) -> tuple[Path, pa.Table]:
    path = tmp_path / "trace.parquet"
    trace_io.write_trace(trace, path)
    return path, pq.read_table(path)


def problems(exc: pytest.ExceptionInfo[errors.ValidationError]) -> list[str]:
    return [issue["message"] for issue in exc.value.context["errors"]]  # type: ignore[index, union-attr]


def test_missing_columns_are_all_reported(written: tuple[Path, pa.Table]) -> None:
    path, table = written
    edited = rewrite(path, table.drop_columns(["est_x", "nav_status"]))
    with pytest.raises(errors.ValidationError) as exc:
        trace_io.read_trace(edited)
    assert problems(exc) == ["missing column est_x", "missing column nav_status"]


def test_wrong_column_type_is_rejected(written: tuple[Path, pa.Table]) -> None:
    path, table = written
    index = table.schema.get_field_index("nav_status")
    cast = table.set_column(index, "nav_status", table.column("nav_status").cast(pa.int32()))
    with pytest.raises(errors.ValidationError, match="nav_status has type int32"):
        trace_io.read_trace(rewrite(path, cast))


def test_nulls_in_required_column_are_rejected(written: tuple[Path, pa.Table]) -> None:
    path, table = written
    index = table.schema.get_field_index("gt_x")
    nulled = table.set_column(index, "gt_x", pa.array([None] * table.num_rows, pa.float64()))
    with pytest.raises(errors.ValidationError, match="gt_x contains nulls"):
        trace_io.read_trace(rewrite(path, nulled))


def test_partially_null_rtf_is_rejected(written: tuple[Path, pa.Table]) -> None:
    path, table = written
    values = table.column("rtf").to_pylist()
    values[3] = None
    index = table.schema.get_field_index("rtf")
    edited = table.set_column(index, pa.field("rtf", pa.float32()), pa.array(values, pa.float32()))
    with pytest.raises(errors.ValidationError, match="partially null"):
        trace_io.read_trace(rewrite(path, edited))


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({"meta": None, "goal_y": None}, "missing file metadata: goal_y, meta"),
        ({"trace_schema_version": 2}, "unsupported trace_schema_version 2"),
        ({"goal_x": b"{not json"}, "not JSON"),
        ({"goal_x": "far", "goal_y": True}, "goal_x must be a number"),
        ({"meta": [1, 2]}, "meta must be a JSON object"),
    ],
)
def test_bad_file_metadata_is_rejected(
    written: tuple[Path, pa.Table], metadata: dict[str, object], message: str
) -> None:
    path, table = written
    with pytest.raises(errors.ValidationError, match=message):
        trace_io.read_trace(rewrite(path, table, **metadata))


def test_trace_invariants_are_reported_as_validation_errors(written: tuple[Path, pa.Table]) -> None:
    path, table = written
    index = table.schema.get_field_index("t")
    backwards = table.set_column(
        index, trace_io.TRACE_SCHEMA.field("t"), pa.array(np.zeros(table.num_rows))
    )
    with pytest.raises(errors.ValidationError, match="strictly increasing"):
        trace_io.read_trace(rewrite(path, backwards))


def test_missing_file_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(errors.NotFoundError):
        trace_io.read_trace(tmp_path / "absent.parquet")


def test_non_parquet_file_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "trace.parquet"
    path.write_text("not parquet")
    with pytest.raises(errors.ValidationError, match="not a readable Parquet file"):
        trace_io.read_trace(path)


def test_meta_must_be_json_serialisable_without_nan(tmp_path: Path) -> None:
    trace = make_trace(n=3, meta={"bad": float("nan")})
    with pytest.raises(ValueError, match="JSON"):
        trace_io.write_trace(trace, tmp_path / "trace.parquet")


# --------------------------------------------------------------------------- validate_trace


def test_regular_20_hz_trace_is_valid() -> None:
    assert (
        trace_io.validate_trace(make_trace(n=40, dt=0.05), min_hz=FR_MIN_HZ, max_gap_s=FR_MAX_GAP_S)
        == ()
    )


def test_slow_trace_is_flagged() -> None:
    found = trace_io.validate_trace(
        make_trace(n=20, dt=0.15), min_hz=FR_MIN_HZ, max_gap_s=FR_MAX_GAP_S
    )
    assert len(found) == 1
    assert "below 10 Hz" in found[0]


def test_gaps_are_flagged_with_location() -> None:
    t = np.arange(40) * 0.05
    t[20:] += 0.5
    found = trace_io.validate_trace(make_trace(n=40, t=t), min_hz=FR_MIN_HZ, max_gap_s=FR_MAX_GAP_S)
    assert found == ("1 gap(s) exceed 0.2 s; largest 0.55 s at t=0.950 s",)


@pytest.mark.parametrize("n", [0, 1])
def test_too_few_samples(n: int) -> None:
    found = trace_io.validate_trace(make_trace(n=n), min_hz=FR_MIN_HZ, max_gap_s=FR_MAX_GAP_S)
    assert found == (f"trace has {n} sample(s); at least 2 needed",)
