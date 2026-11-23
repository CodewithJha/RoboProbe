# T-103 — kinematic2d reference set (pre-registration)

Smoke reference (``n = 8``, seed ``11``) is asserted in ``test_reference_set.py``.
Full artefact: ``reference/warehouse_v1_k2d.parquet`` (``n = 20000``, seed ``20261119``).

Generate and record hash on a release machine:

```bash
uv run roboprobe reference generate --output ./data/artifacts/reference/warehouse_v1_k2d.parquet
```

Manifest is written beside the parquet (``.manifest.json``) with the SHA-256 digest.

The [EXP-01 warehouse reference](EXP-01-reference.md) records the recovered
20,000-row Parquet, its checksum, and sample verification.

## Import reviewed mode assignments

Cluster the failing rows and inspect representative scenarios and traces before
assigning ground-truth modes. Keep the raw dataset and record its SHA-256 from
the generated manifest. Prepare a JSON file whose `source_sha256` is that digest
and whose `labels` object maps failing row ordinals to reviewed `GT-...` mode IDs.
Set a reviewed ordinal to `null` when it has no accepted mode. Omit ordinals still awaiting review.

```bash
roboprobe reference label --reviewed-labels reviewed.json \
  --output warehouse_v1_k2d_reviewed.parquet warehouse_v1_k2d.parquet
```

The output has a manifest with its own checksum. Use a separate output file to
keep the original dataset available for independent review.

## Score EXP-07 discovery offline

Use the original reference and its manifest for each arm. The scorer verifies the frozen
design hash, budget, and exact space and model versions in the run and reference manifests.

```bash
roboprobe --json reference score runs.parquet --run-manifest runs.manifest.json \
  --reference reference.parquet --reviewed-labels reviewed.json > discovery.json
```

The output records artifact hashes and per-cell scores using the preregistered unit L2 radius of 0.05. Incomplete campaigns and matches to an unreviewed failure leave scores pending.
MET-09 also needs a complete mode inventory. Omit `--reviewed-labels` to inspect review gaps.
