"""Reconstruct paired MET-07 labels using archived original study rows and GP settings."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from statistics import mean

import numpy as np
from scipy.stats import qmc

from roboprobe.core.settings.analysis import RiskSettings
from roboprobe.core.settings.selection import GpDefaults
from roboprobe.core.clock import SystemClock
from roboprobe.metrics.campaign_metrics import robustness_delta
from roboprobe.risk.mapper import REGION_FAILURE, REGION_SAFE, REGION_UNCERTAIN, RiskMapper
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.selection.surrogate import RobustnessGP

root = Path.cwd()
out = Path(sys.argv[1])
data = json.loads((out / "exp05-verified.json").read_text())
space = ScenarioSpace.from_yaml(root / "configs/scenario_spaces/warehouse_v1.yaml", base_dir=root)
expected = ["safe", "uncertain", "failure"]
names = {int(REGION_SAFE): "SAFE", int(REGION_UNCERTAIN): "UNCERTAIN", int(REGION_FAILURE): "FAILURE"}
paired_score = {int(REGION_SAFE): 1.0, int(REGION_UNCERTAIN): 0.5, int(REGION_FAILURE): 0.0}
seed_root = 20261119
n_boot = 5000
fitted = {}

for meta in data["cells"]:
    arm, rep, seed = meta["arm"], meta["replicate"], meta["seed"]
    collection = json.loads((out / f"{arm}-rep{rep}-collection.json").read_text())
    cell = collection["cell"]
    scenario_space = space.with_pins(cell.get("pins", {}))
    rows = json.loads((out / f"{arm}-rep{rep}-rows.json").read_text())
    # The campaign repository serves analysis in UUID order.
    training = sorted((r for r in rows if r["robustness"] is not None), key=lambda r: r["id"])
    x = np.asarray([row["x_unit"] for row in training], dtype=np.float64)
    y = np.asarray([row["robustness"] for row in training], dtype=np.float64)
    model = RobustnessGP(scenario_space.dim, seed=seed, gp=GpDefaults(), metrics=None, clock=SystemClock())
    model.fit(x, y)
    n = meta["volumes"]["n"]
    points = qmc.Sobol(d=scenario_space.dim, scramble=True, seed=seed).random(n)
    regions = RiskMapper(model, scenario_space, RiskSettings().thresholds).classify(points)
    fractions = (np.bincount(regions, minlength=3) / n).tolist()
    hosted = [meta["volumes"][name] for name in expected]
    print(f"{arm} {rep}: {fractions=} {hosted=}", flush=True)
    if hosted != fractions:
        raise RuntimeError(f"Reconstructed volumes differ from original hosted risk output for {arm} {rep}")
    fitted[(arm, rep)] = points, regions

reps = []
delta_points = []
rng = np.random.default_rng(seed_root)
for rep in range(3):
    points_a, regions_a = fitted[("profile_A", rep)]
    points_b, regions_b = fitted[("profile_B", rep)]
    assert np.array_equal(points_a, points_b)
    labels_a = [names[int(region)] for region in regions_a]
    labels_b = [names[int(region)] for region in regions_b]
    delta, interval = robustness_delta(labels_a, labels_b, n_resamples=n_boot, rng=rng)
    assert np.isclose(delta, data["matched_robustness_deltas"][rep])
    diffs = np.asarray([paired_score[int(b)] - paired_score[int(a)]
                        for a, b in zip(regions_a, regions_b, strict=True)], dtype=np.float64)
    delta_points.append(diffs)
    basis = out / f"profile-pair-rep{rep}-sobol.npz"
    np.savez_compressed(basis, points=points_a, profile_a=regions_a, profile_b=regions_b)
    reps.append({"replicate": rep, "delta": delta, "paired_point_bootstrap_95_ci": interval,
                 "n_points": len(points_a), "basis_sha256": hashlib.sha256(basis.read_bytes()).hexdigest()})

bootstrap = []
for _ in range(n_boot):
    bootstrap.append(mean(float(np.mean(points[rng.integers(0, len(points), size=len(points))]))
                          for points in delta_points))
seed_deltas = np.array([entry["delta"] for entry in reps])
seed_bootstrap = seed_deltas[np.indices((3, 3, 3)).reshape(3, -1)].mean(axis=0)
result = {
    "replicates": reps,
    "mean_paired_delta": float(seed_deltas.mean()),
    "stratified_point_bootstrap_95_ci": np.quantile(bootstrap, [.025, .975]).tolist(),
    "descriptive_seed_bootstrap_95_ci": np.quantile(seed_bootstrap, [.025, .975]).tolist(),
    "bootstrap_samples": n_boot, "bootstrap_seed": seed_root,
    "note": "Point intervals are conditional on the fitted models and paired Sobol points. Only three independent campaign seed pairs were registered.",
}
(out / "exp05-paired-met07.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
