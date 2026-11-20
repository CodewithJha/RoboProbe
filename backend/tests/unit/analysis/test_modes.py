"""Tests for :mod:`roboprobe.analysis.modes` (T-071a, docs/09 §3.3)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from tests.unit.analysis.conftest import make_run, uid

from roboprobe.analysis.clustering import FailureClusterer
from roboprobe.analysis.features import FailureFeatureBuilder
from roboprobe.analysis.modes import ModeSummarizer, build_label
from roboprobe.analysis.settings import ClustererSettings, LabelLexicon
from roboprobe.analysis.types import ClusteringResult, FailureModeSummary, ParamRange
from roboprobe.core.settings.analysis import FeatureWeights
from roboprobe.core.types import FailureClass

pytestmark = pytest.mark.unit

GOLDEN = Path(__file__).with_name("multi_mode_6d_summaries.json")


def test_label_format_matches_doc(space: object) -> None:
    summary = FailureModeSummary(
        code="FM-01",
        size=3,
        primary_class=FailureClass.COL,
        class_mix={FailureClass.COL: 1.0},
        ranges={
            "robot.max_speed": ParamRange(unit="m/s", q05=0.38, q95=0.48, space_coverage=0.2),
            "env.illuminance": ParamRange(unit="lux", q05=8.0, q95=30.0, space_coverage=0.15),
            "sensor.lidar_noise_std": ParamRange(unit="m", q05=0.07, q95=0.1, space_coverage=0.3),
        },
        characteristic=frozenset({"robot.max_speed", "env.illuminance", "sensor.lidar_noise_std"}),
        medoid_run_id=uid(1),
        minimal_run_id=uid(1),
        minimal_values={},
        member_run_ids=(uid(1), uid(2), uid(3)),
        label="",
        provisional=False,
    )
    label = build_label(summary, space)  # type: ignore[arg-type]
    assert label.startswith("F-COL | ")
    assert "speed high" in label
    assert "light low" in label
    assert "noise high" in label


def test_characteristic_coverage(space: object, monkeypatch: pytest.MonkeyPatch) -> None:
    del monkeypatch
    runs = [
        make_run(id=uid(i), values=_tight_speed(space, 0.45))  # type: ignore[arg-type]
        for i in range(5)
    ]
    x = np.vstack([space.to_unit(r.values) for r in runs])  # type: ignore[union-attr]
    result = ClusteringResult(
        labels=np.zeros(5, dtype=np.intp),
        probabilities=np.ones(5),
        outlier_scores=np.zeros(5),
        method="hdbscan",
        min_cluster_size=3,
        provisional=False,
        run_ids=tuple(r.id for r in runs),
        X=x,
    )
    tight = ModeSummarizer(characteristic_coverage=0.5).summarize(result, runs, space)  # type: ignore[arg-type]
    loose = ModeSummarizer(characteristic_coverage=0.01).summarize(result, runs, space)  # type: ignore[arg-type]
    assert "robot.max_speed" in tight[0].characteristic
    assert (
        tight[0].characteristic >= loose[0].characteristic
        or loose[0].characteristic <= tight[0].characteristic
    )


def _tight_speed(space: object, speed: float) -> dict[str, float]:
    values = dict(space.nominal_values())  # type: ignore[union-attr]
    values["robot.max_speed"] = speed
    return values


def test_medoid_and_minimal_on_five_runs(space: object) -> None:
    nominal = space.nominal_values()  # type: ignore[union-attr]
    runs = []
    for i, speed in enumerate([0.45, 0.44, 0.43, 0.42, 0.32]):
        values = dict(nominal)
        values["robot.max_speed"] = speed
        runs.append(make_run(id=uid(i + 1), values=values))
    x = np.vstack([space.to_unit(r.values) for r in runs])  # type: ignore[union-attr]
    result = ClusteringResult(
        labels=np.zeros(5, dtype=np.intp),
        probabilities=np.ones(5),
        outlier_scores=np.zeros(5),
        method="hdbscan",
        min_cluster_size=3,
        provisional=False,
        run_ids=tuple(r.id for r in runs),
        X=x,
    )
    [summary] = ModeSummarizer(characteristic_coverage=0.5).summarize(result, runs, space)  # type: ignore[arg-type]
    assert summary.minimal_run_id == uid(5)
    assert summary.medoid_run_id in {r.id for r in runs}


def test_noise_never_becomes_a_mode(space: object) -> None:
    runs = [make_run(id=uid(1)), make_run(id=uid(2))]
    x = np.vstack([space.to_unit(r.values) for r in runs])  # type: ignore[union-attr]
    result = ClusteringResult(
        labels=np.array([-1, -1], dtype=np.intp),
        probabilities=np.zeros(2),
        outlier_scores=np.ones(2),
        method="hdbscan",
        min_cluster_size=3,
        provisional=False,
        run_ids=(uid(1), uid(2)),
        X=x,
    )
    assert ModeSummarizer(characteristic_coverage=0.5).summarize(result, runs, space) == []  # type: ignore[arg-type]


def test_provisional_flag_propagated(space: object) -> None:
    runs = [make_run(id=uid(i + 1)) for i in range(4)]
    x = np.vstack([space.to_unit(r.values) for r in runs])  # type: ignore[union-attr]
    result = ClusteringResult(
        labels=np.zeros(4, dtype=np.intp),
        probabilities=np.ones(4),
        outlier_scores=np.zeros(4),
        method="class_fallback",
        min_cluster_size=3,
        provisional=True,
        run_ids=tuple(r.id for r in runs),
        X=x,
    )
    [summary] = ModeSummarizer(characteristic_coverage=0.5).summarize(result, runs, space)  # type: ignore[arg-type]
    assert summary.provisional is True


def test_golden_multi_mode_snapshot(space: object) -> None:
    rng = np.random.Generator(np.random.PCG64(7))
    runs = []
    for k, (speed, light) in enumerate([(0.45, 10.0), (0.12, 800.0)]):
        for j in range(8):
            values = dict(space.nominal_values())  # type: ignore[union-attr]
            values["robot.max_speed"] = float(np.clip(speed + rng.normal(0, 0.01), 0.1, 0.5))
            values["env.illuminance"] = float(np.clip(light + rng.normal(0, 1.0), 5.0, 1000.0))
            runs.append(make_run(id=uid(k * 8 + j + 1), values=values))
    features = FailureFeatureBuilder(FeatureWeights()).build(runs, space)  # type: ignore[arg-type]
    clustered = FailureClusterer(
        ClustererSettings(min_failures_for_clustering=6, min_cluster_size_floor=3)
    ).fit(features)
    summaries = ModeSummarizer(
        characteristic_coverage=0.5, lexicon=LabelLexicon(), seed=7
    ).summarize(
        clustered,
        runs,
        space,  # type: ignore[arg-type]
    )
    payload = [
        {
            "size": s.size,
            "primary": s.primary_class.value,
            "label": s.label,
            "characteristic": sorted(s.characteristic),
        }
        for s in summaries
    ]
    if not GOLDEN.exists():
        GOLDEN.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    expected = json.loads(GOLDEN.read_text())
    assert payload == expected
