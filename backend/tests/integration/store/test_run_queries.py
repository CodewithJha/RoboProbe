"""Stable filtered keysets on PostgreSQL (T-081d, FR-API-001)."""

from collections.abc import Callable

import pytest
from tests.integration.store._seed import seed_campaign

from roboprobe.store.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "sort", ["ordinal", "-ordinal", "finished_at", "-finished_at", "robustness", "-robustness"]
)
def test_keyset_pages_have_no_gaps_or_duplicates(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
    sort: str,
) -> None:
    with uow_factory() as uow:
        cid, ids = seed_campaign(uow, n_runs=4)
        seen = []
        cursor = None
        while True:
            page = uow.runs.query_for_campaign(
                cid, limit=1, cursor=cursor, sort=sort, status="PENDING"
            )
            seen.extend(row.id for row in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert len(seen) == len(set(seen)) == len(ids)
        assert set(seen) == set(ids)
        if sort.endswith("ordinal"):
            ordinals = [uow.runs.get(rid).ordinal for rid in seen]
            assert ordinals == sorted(ordinals, reverse=sort.startswith("-"))
        assert not uow.runs.query_for_campaign(cid, limit=10, tags=("missing",)).items
