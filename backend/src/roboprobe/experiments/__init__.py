"""Experiment planning and execution across strategies and seeds.

Layer: Application (L3). See docs/16 §2 for the allowed import directions.
"""

from roboprobe.experiments.planner import (
    CampaignSpec,
    ComparabilityKey,
    ExperimentDesign,
    StrategyVariant,
    check_comparable,
    load_design,
    plan,
)
from roboprobe.experiments.runner import ExperimentRunner, build_comparison, export_raw_parquet

__all__ = [
    "CampaignSpec",
    "ComparabilityKey",
    "ExperimentDesign",
    "ExperimentRunner",
    "StrategyVariant",
    "build_comparison",
    "check_comparable",
    "export_raw_parquet",
    "load_design",
    "plan",
]
