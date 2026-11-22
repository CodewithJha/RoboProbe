"""Dashboard reads against the isolated T-107 benchmark campaign."""

from __future__ import annotations

import csv
import os
from itertools import cycle
from pathlib import Path
from typing import TYPE_CHECKING

from locust import HttpUser, between, events, task
from locust.stats import PERCENTILES_TO_REPORT, StatsCSV

if TYPE_CHECKING:
    from collections.abc import Iterator

    from locust.env import Environment

_CAMPAIGNS = "/api/v1/campaigns"
_RUNS_GROUP = "/api/v1/campaigns/{id}/runs"
_RUN_GROUP = "/api/v1/runs/{id}"
_MODES_GROUP = "/api/v1/campaigns/{id}/modes"
_PAGE_SIZE = 10
_PAGE_DEPTH = 5
_REQUEST_TIMEOUT_S = 10
_THINK_SECONDS = (0.2, 1.0)
# The FAIL filter also has at least five pages in the documented benchmark seed.
_VIEWS = (
    {"sort": "-ordinal"},
    {"sort": "robustness", "status": "DONE", "verdict": "PASS"},
    {"sort": "-finished_at", "verdict": "FAIL"},
)


@events.init.add_listener
def _register_complete_csv(environment: Environment, **_kwargs: object) -> None:
    options = environment.parsed_options
    if options is None or not options.csv_prefix:
        return
    report = Path(f"{options.csv_prefix}_complete_stats.csv")

    @environment.events.quit.add_listener
    def _write_complete_stats(**_event: object) -> None:
        # --csv is periodic. Once the runner stops, export every measured request.
        with report.open("w", encoding="utf-8", newline="") as stream:
            StatsCSV(environment, PERCENTILES_TO_REPORT).requests_csv(csv.writer(stream))


class DashboardUser(HttpUser):
    """Model dashboard navigation, with most task time spent reading the run list."""

    wait_time = between(*_THINK_SECONDS)

    def on_start(self) -> None:
        self._campaign = f"{_CAMPAIGNS}/{os.environ['ROBOPROBE_PERF_CAMPAIGN_ID']}"
        self._views = cycle(_VIEWS)
        self._run_ids: Iterator[str] = iter(())
        initial = self._read_page({"limit": _PAGE_SIZE, "sort": "-ordinal"}, set())
        if initial is not None:
            self._run_ids = cycle(initial[0])

    @task(2)
    def campaign_list(self) -> None:
        self.client.get(_CAMPAIGNS, name=_CAMPAIGNS, timeout=_REQUEST_TIMEOUT_S)

    @task(5)
    def browse_runs(self) -> None:
        params: dict[str, str | int] = {"limit": _PAGE_SIZE, **next(self._views)}
        seen: set[str] = set()
        for number in range(_PAGE_DEPTH):
            result = self._read_page(params, seen, has_next=number < _PAGE_DEPTH - 1)
            if result is None:
                return
            ids, cursor = result
            seen.update(ids)
            self._run_ids = cycle(ids)
            if cursor is not None:
                params["cursor"] = cursor

    @task(2)
    def run_detail(self) -> None:
        run_id = next(self._run_ids, None)
        if run_id is not None:
            self.client.get(f"/api/v1/runs/{run_id}", name=_RUN_GROUP, timeout=_REQUEST_TIMEOUT_S)

    @task(1)
    def campaign_modes(self) -> None:
        self.client.get(f"{self._campaign}/modes", name=_MODES_GROUP, timeout=_REQUEST_TIMEOUT_S)

    def _read_page(
        self, params: dict[str, str | int], seen: set[str], *, has_next: bool = False
    ) -> tuple[list[str], str | None] | None:
        with self.client.get(
            f"{self._campaign}/runs",
            name=_RUNS_GROUP,
            params=params,
            timeout=_REQUEST_TIMEOUT_S,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Runs page returned HTTP {response.status_code}")
                return None
            try:
                page = response.json()
                ids = [entry["id"] for entry in page["items"]]
                cursor = page["next_cursor"]
            except (KeyError, TypeError, ValueError):
                response.failure("Expected a JSON page with run IDs and a next_cursor")
                return None
            if not ids or any(not isinstance(run_id, str) for run_id in ids):
                response.failure("Runs page is empty or contains invalid IDs")
                return None
            if len(set(ids)) != len(ids) or seen.intersection(ids):
                response.failure("Runs page repeated IDs")
                return None
            if (has_next or cursor is not None) and (not isinstance(cursor, str) or not cursor):
                response.failure("Runs page omitted a usable cursor before reaching the fifth page")
                return None
            return ids, cursor
