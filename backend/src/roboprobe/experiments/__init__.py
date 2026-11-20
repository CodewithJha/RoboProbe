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

__all__ = [
    "CampaignSpec",
    "ComparabilityKey",
    "ExperimentDesign",
    "StrategyVariant",
    "check_comparable",
    "load_design",
    "plan",
]
