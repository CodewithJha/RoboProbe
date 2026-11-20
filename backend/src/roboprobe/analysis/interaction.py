"""Plan and conclude confirmatory interaction tests (docs/09 §6). Pure: no queue.

Implements: FR-ANA-005
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations
from typing import Literal
from uuid import UUID

from roboprobe.analysis._const import PAIR_MIN_SIZE
from roboprobe.analysis.settings import LabelLexicon
from roboprobe.analysis.types import (
    AnalysisRun,
    ConfirmScenario,
    FailureModeSummary,
    InteractionVerdict,
)
from roboprobe.core.seeding import derive_seed
from roboprobe.core.settings.analysis import InteractionSettings
from roboprobe.core.types import Verdict
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["InteractionTester"]

_CONFIRM = "confirm"
_FULL_KEY = "full"


class InteractionTester:
    """Build confirmatory scenarios from ``x_min`` and score the interaction claim."""

    def __init__(
        self,
        settings: InteractionSettings,
        campaign_seed: int,
        lexicon: LabelLexicon | None = None,
    ) -> None:
        """Bind repeats/success ratio, campaign seed and label lexicon."""
        self._settings = settings
        self._seed = campaign_seed
        self._lexicon = lexicon or LabelLexicon()

    def plan(self, mode: FailureModeSummary, space: ScenarioSpace) -> list[ConfirmScenario]:
        """Singles, pairs (if |C| ≥ 3), and full, each repeated ``repeats`` times.

        Implements: FR-ANA-005
        """
        x_min = mode.minimal_values
        characteristic = _capped(mode, space, self._lexicon.interaction_cap)
        subsets = _subsets(characteristic)
        nominal = space.nominal_values()
        out: list[ConfirmScenario] = []
        for subset in subsets:
            values = dict(nominal)
            active = subset if subset else frozenset(characteristic)
            for pid in active:
                values[pid] = x_min[pid]
            scenario = space.make_scenario(values)
            key = _subset_key(subset)
            for rep in range(self._settings.repeats):
                seed = derive_seed(self._seed, _CONFIRM, mode.code or "", key, rep)
                out.append(
                    ConfirmScenario(
                        scenario=scenario,
                        subset=subset,
                        tags=(_CONFIRM, mode.code),
                        seed=seed,
                        repeat=rep,
                    )
                )
        return out

    def conclude(
        self, mode: FailureModeSummary, confirm_runs: Sequence[AnalysisRun]
    ) -> InteractionVerdict:
        """Score subset failure ratios and emit CONFIRMED / NOT_INTERACTION / INCONCLUSIVE.

        Implements: FR-ANA-005
        """
        repeats = self._settings.repeats
        by_key: dict[str, list[AnalysisRun]] = {}
        for run in confirm_runs:
            key = _subset_key(run.subset) if run.subset is not None else _FULL_KEY
            by_key.setdefault(key, []).append(run)
        ratios: dict[str, float] = {}
        evidence: list[UUID] = []
        inconclusive = False
        for key, group in by_key.items():
            valid = [r for r in group if r.verdict is not Verdict.INVALID]
            if len(valid) < repeats:
                inconclusive = True
            fails = [r for r in valid if r.verdict is Verdict.FAIL]
            denom = len(valid) or 1
            ratios[key] = len(fails) / denom
            evidence.extend(r.id for r in fails)
        if inconclusive:
            return InteractionVerdict(
                status="INCONCLUSIVE",
                order=None,
                params=(),
                ratios=ratios,
                evidence_run_ids=tuple(evidence),
            )
        cut = self._settings.success_ratio
        singles = [k for k in ratios if k != _FULL_KEY and "," not in k]
        full_ratio = ratios.get(_FULL_KEY, 0.0)
        single_hit = any(ratios.get(k, 0.0) >= cut for k in singles)
        interaction = full_ratio >= cut and not single_hit
        order, params = _smallest_failing(ratios, cut)
        status: Literal["CONFIRMED", "NOT_INTERACTION", "INCONCLUSIVE"]
        status = "CONFIRMED" if interaction else "NOT_INTERACTION"
        return InteractionVerdict(
            status=status,
            order=order,
            params=params,
            ratios=ratios,
            evidence_run_ids=tuple(evidence),
        )


def _capped(mode: FailureModeSummary, space: ScenarioSpace, cap: int) -> tuple[str, ...]:
    ranked = sorted(
        mode.characteristic,
        key=lambda pid: (mode.ranges[pid].space_coverage if pid in mode.ranges else 1.0, pid),
    )[:cap]
    return tuple(p for p in ranked if p in {spec.id for spec in space.params})


def _subsets(characteristic: Sequence[str]) -> list[frozenset[str]]:
    c = list(characteristic)
    out: list[frozenset[str]] = [frozenset({p}) for p in c]
    if len(c) >= PAIR_MIN_SIZE:
        out.extend(frozenset(pair) for pair in combinations(c, 2))
    out.append(frozenset())
    return out


def _subset_key(subset: frozenset[str] | Sequence[str] | None) -> str:
    if not subset:
        return _FULL_KEY
    items = sorted(subset)
    return ",".join(items) if items else _FULL_KEY


def _smallest_failing(ratios: dict[str, float], cut: float) -> tuple[int | None, tuple[str, ...]]:
    best: tuple[int, tuple[str, ...]] | None = None
    for key, ratio in ratios.items():
        if ratio < cut:
            continue
        params = () if key == _FULL_KEY else tuple(key.split(","))
        order = len(params) if params else 0
        if best is None or order < best[0] or (order == best[0] and params < best[1]):
            best = (order, params)
    if best is None:
        return None, ()
    return best[0] if best[0] else None, best[1]
