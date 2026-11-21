# T-103 — kinematic2d reference set (pre-registration)

Smoke reference (``n = 8``, seed ``11``) is asserted in ``test_reference_set.py``.
Full artefact: ``reference/warehouse_v1_k2d.parquet`` (``n = 20000``, seed ``20261119``).

Generate and record hash on a release machine:

```bash
uv run roboprobe reference generate --output ./data/artifacts/reference/warehouse_v1_k2d.parquet
```

Manifest is written beside the parquet (``.manifest.json``) with the SHA-256 digest.
