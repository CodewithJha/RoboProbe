import csv
from pathlib import Path

import pytest
from tests.perf.check_stats import check

pytestmark = pytest.mark.unit

_GROUP = "/api/v1/campaigns/{id}/runs"
_HEADER = ("Type", "Name", "Request Count", "Failure Count", "95%")


def _write_stats(target: Path, rows: list[tuple[str, str, str, str, str]]) -> None:
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(_HEADER)
        writer.writerows(rows)


@pytest.mark.parametrize(
    ("stats_values", "status", "message"),
    [
        (("20", "0", "200"), 0, "PASS"),
        (("20", "0", "200.01"), 1, "p95 above limit"),
        (("20", "1", "50"), 1, "request failures"),
        (("0", "0", "0"), 1, "no requests"),
        (("20", "0", "nan"), 1, "invalid statistics"),
    ],
)
def test_gate_uses_configured_limit_and_reports_failures(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    stats_values: tuple[str, str, str],
    status: int,
    message: str,
) -> None:
    stats = tmp_path / "perf_stats.csv"
    _write_stats(stats, [("GET", _GROUP, *stats_values)])
    assert check(stats, {_GROUP: 200}) == status
    output = capsys.readouterr().out
    assert _GROUP in output and "p95 (ms)" in output and message in output


def test_aggregate_row_cannot_hide_an_unsampled_group(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stats = tmp_path / "perf_stats.csv"
    _write_stats(stats, [("", "Aggregated", "100", "0", "8")])
    assert check(stats, {_GROUP: 200}) == 1
    assert "missing samples" in capsys.readouterr().out


def test_duplicate_group_rows_fail_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stats = tmp_path / "perf_stats.csv"
    _write_stats(stats, [("GET", _GROUP, "20", "0", "50")] * 2)
    assert check(stats, {_GROUP: 200}) == 1
    assert "duplicate rows" in capsys.readouterr().out
