# T-103 — kinematic2d reference set (pre-registration)

Smoke reference (``n = 8``, seed ``11``) is asserted in ``test_reference_set.py``.
Full artefact: ``reference/warehouse_v1_k2d.parquet`` (``n = 20000``, seed ``20261119``).

Generate and record hash on a release machine:

```bash
uv run roboprobe reference generate --output ./data/artifacts/reference/warehouse_v1_k2d.parquet
```

Manifest is written beside the parquet (``.manifest.json``) with the SHA-256 digest.

## Import reviewed mode assignments

Cluster the failing rows and inspect representative scenarios and traces before
assigning ground-truth modes. Keep the raw dataset and record its SHA-256 from
the generated manifest. Prepare a JSON file whose `source_sha256` is that digest
and whose `labels` object maps failing row ordinals to reviewed `GT-...` mode IDs.
Omit ordinals that have no accepted ground-truth mode.

```bash
roboprobe reference label --reviewed-labels reviewed.json \
  --output warehouse_v1_k2d_reviewed.parquet warehouse_v1_k2d.parquet
```

The output has a manifest with its own checksum. Use a separate output file to
keep the original dataset available for independent review.
