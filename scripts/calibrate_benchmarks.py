#!/usr/bin/env python3
"""Calibrate selection benchmark thresholds on analytic functions only (T-061).

Runs a fixed seed list against branin_falsify / multi_mode_6d via the registered
strategies, prints raw medians, and never touches the EXP-01 evaluation space.

Usage (from repository root, after ``uv sync`` in ``backend/``)::

    uv run --directory backend python ../scripts/calibrate_benchmarks.py
    uv run --directory backend python ../scripts/calibrate_benchmarks.py --seeds 5 --budget 40
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

from uuid import uuid4

import numpy as np

from roboprobe import __version__
from roboprobe.core.types import Observation, Verdict
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.selection.base import StrategyContext
from roboprobe.selection.benchmarks import branin_falsify, label_mode, multi_mode_6d
from roboprobe.selection.registry import create


def _obs(unit: np.ndarray, rho: float, verdict: Verdict) -> Observation:
    return Observation(
        x_unit=tuple(float(v) for v in unit),
        robustness=float(rho),
        verdict=verdict,
        failure_class=None,
        run_id=uuid4(),
    )

REPO = Path(__file__).resolve().parents[1]
SPACE = REPO / "configs" / "scenario_spaces" / "warehouse_v1.yaml"
DEFAULT_SEEDS = tuple(range(20))


def _space(dim: int) -> ScenarioSpace:
    space = ScenarioSpace.from_yaml(SPACE, base_dir=REPO)
    if dim < space.dim:
        values = space.nominal_values()
        pins = {p.id: values[p.id] for p in space.params[dim:]}
        space = space.with_pins(pins)
    return space


def _campaign(
    strategy_id: str,
    seed: int,
    budget: int,
    dim: int,
    *,
    fn: str,
) -> dict[str, object]:
    space = _space(dim)
    strat = create(
        strategy_id,
        StrategyContext(space=space, budget=budget, seed=seed, batch_size=4, params={}),
    )
    history = []
    first_fail: int | None = None
    modes: set[str] = set()
    while len(history) < budget:
        proposals = strat.propose(history, [], min(4, budget - len(history)))
        if not proposals:
            break
        for proposal in proposals:
            unit = space.to_unit(proposal.scenario.values)
            if fn == "branin":
                rho = branin_falsify(unit)
            else:
                rho = multi_mode_6d(unit, noise=0.0)
                label = label_mode(unit)
                if label is not None:
                    modes.add(label)
            verdict = Verdict.FAIL if rho < 0.0 else Verdict.PASS
            if verdict is Verdict.FAIL and first_fail is None:
                first_fail = len(history) + 1
            history.append(_obs(unit, float(rho), verdict))
            strat.observe(history[-1])
    return {"first_fail": first_fail, "modes": sorted(modes), "n": len(history)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=len(DEFAULT_SEEDS))
    parser.add_argument("--budget", type=int, default=150)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO / "docs" / "evidence" / "T-061-raw.json",
    )
    args = parser.parse_args()
    seeds = tuple(range(args.seeds))
    rows: dict[str, object] = {
        "python": sys.version,
        "platform": platform.platform(),
        "roboprobe": __version__,
        "seeds": list(seeds),
        "budget": args.budget,
        "results": {},
    }
    for strategy_id, dim, fn in (
        ("S-BO", 2, "branin"),
        ("S-PROBE", 6, "multi"),
        ("S-RANDOM", 6, "multi"),
        ("S-LSE", 6, "multi"),
    ):
        key = f"{strategy_id}:{fn}"
        print(f"calibrating {key} …", flush=True)
        runs = [_campaign(strategy_id, seed, args.budget, dim, fn=fn) for seed in seeds]
        first = [int(r["first_fail"]) for r in runs if r["first_fail"] is not None]
        mode_counts = [len(r["modes"]) for r in runs]  # type: ignore[arg-type]
        rows["results"][key] = {  # type: ignore[index]
            "runs": runs,
            "median_first_fail": float(np.median(first)) if first else None,
            "mean_modes": float(np.mean(mode_counts)) if mode_counts else None,
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
