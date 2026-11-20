"""ORM schema matches docs/11 §3 (T-010a)."""

from __future__ import annotations

import pytest
from sqlalchemy import Connection, text

from roboprobe.store.orm import Base, CampaignRow

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "scenario_spaces",
    "sut_profiles",
    "experiments",
    "campaigns",
    "workers",
    "runs",
    "oracle_results",
    "strategy_states",
    "analyses",
    "failure_modes",
    "failure_mode_members",
    "risk_maps",
    "artifacts",
    "events",
}


def test_create_all_tables(pg_connection: Connection) -> None:
    Base.metadata.create_all(pg_connection)
    names = set(
        pg_connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).scalars()
    )
    assert names >= EXPECTED_TABLES
    indexes = set(
        pg_connection.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        ).scalars()
    )
    for name in (
        "ix_runs_queue",
        "ix_runs_campaign_status",
        "ix_runs_campaign_verdict",
        "ix_runs_scenario_hash",
        "ix_campaigns_status",
        "ix_campaigns_experiment",
        "ix_artifacts_run",
        "ix_artifacts_sha",
        "ix_events_campaign",
    ):
        assert name in indexes


def test_check_rejects_bad_campaign_status(pg_connection: Connection) -> None:
    Base.metadata.create_all(pg_connection)
    pg_connection.execute(
        text(
            "INSERT INTO sut_profiles (id, backend, config, config_hash) "
            "VALUES ('p', 'kinematic2d', '{}'::jsonb, 'h')"
        )
    )
    pg_connection.execute(
        text(
            "INSERT INTO scenario_spaces (id, version, name, definition) "
            "VALUES ('s', 'v', 'n', '{}'::jsonb)"
        )
    )
    with pytest.raises(Exception, match="status"):
        pg_connection.execute(
            text(
                "INSERT INTO campaigns (id, name, space_id, space_version, sut_profile_id, "
                "backend, strategy_id, seed, budget, oracle_config, status) VALUES "
                "(gen_random_uuid(), 'c', 's', 'v', 'p', 'kinematic2d', 'S-RANDOM', 1, 10, "
                "'{}'::jsonb, 'NOPE')"
            )
        )
    assert CampaignRow.__tablename__ == "campaigns"
