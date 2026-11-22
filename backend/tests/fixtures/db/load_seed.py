#!/usr/bin/env python3
"""Load the committed T-107 fixture into a fresh, migrated PostgreSQL database.

Use a dedicated database and an empty artefact directory. Run
`roboprobe db upgrade` against that database before loading the fixture.
"""

from __future__ import annotations

import argparse
import sys
import tarfile
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Final

import psycopg
import zstandard
from sqlalchemy.engine import make_url

FIXTURE_DIR: Final = Path(__file__).resolve().parent
SEED_SQL: Final = "seed_small.sql"
SEED_ARTIFACTS: Final = "seed_small_artifacts.tar.zst"
MAX_ARCHIVE_BYTES: Final = 2_000_000


def _postgres_dsn(database_url: str) -> str:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql" or not url.database:
        msg = "the fixture requires an explicit PostgreSQL database"
        raise ValueError(msg)
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _extract_archive(path: Path, destination: Path) -> None:
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        msg = "the seed artefact archive exceeds 2 MB"
        raise ValueError(msg)

    extracted: set[PurePosixPath] = set()
    with (
        path.open("rb") as source,
        zstandard.ZstdDecompressor().stream_reader(source) as decompressed,
        tarfile.open(fileobj=decompressed, mode="r|") as archive,
    ):
        for member in archive:
            name = PurePosixPath(member.name)
            if (
                name.is_absolute()
                or ".." in name.parts
                or "\\" in member.name
                or not name.parts
                or name.parts[0] != "sha256"
                or not (member.isfile() or member.isdir())
                or name in extracted
            ):
                msg = "unexpected path or entry type in the seed artefact archive"
                raise ValueError(msg)
            archive.extract(member, path=destination, filter="data")
            extracted.add(name)


def _require_empty_root(artifact_root: Path) -> None:
    if artifact_root.is_symlink() or (
        artifact_root.exists() and (not artifact_root.is_dir() or any(artifact_root.iterdir()))
    ):
        msg = "the seed artefact directory must be empty"
        raise ValueError(msg)


def load_seed(
    database_url: str,
    artifact_root: Path,
    *,
    fixture_dir: Path = FIXTURE_DIR,
) -> None:
    """Restore fixture rows and their artefacts into otherwise empty test storage.

    Args:
        database_url: PostgreSQL or SQLAlchemy PostgreSQL URL for a migrated scratch database.
        artifact_root: Empty or nonexistent local artefact directory.
        fixture_dir: Directory containing the trusted, generated SQL and tar.zst fixtures.

    Raises:
        ValueError: Target storage is populated, the database is unmigrated, or the archive
            does not conform to the local artefact layout.
    """
    database_dsn = _postgres_dsn(database_url)
    artifact_root = artifact_root.absolute()
    _require_empty_root(artifact_root)
    restore_sql = (fixture_dir / SEED_SQL).read_text(encoding="utf-8")
    artifact_root.parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix=".seed-restore-", dir=artifact_root.parent) as temp:
        staged = Path(temp) / "artifacts"
        staged.mkdir()
        _extract_archive(fixture_dir / SEED_ARTIFACTS, staged)

        with psycopg.connect(database_dsn) as connection:
            relation = connection.execute("SELECT to_regclass('public.campaigns')").fetchone()
            if relation is None or relation[0] is None:
                msg = "migrate the fixture database before loading the seed"
                raise ValueError(msg)
            connection.execute("LOCK TABLE public.campaigns IN SHARE ROW EXCLUSIVE MODE")
            if connection.execute("SELECT 1 FROM public.campaigns LIMIT 1").fetchone():
                msg = "the seed database already contains campaigns"
                raise ValueError(msg)
            connection.execute(restore_sql, prepare=False)

            _require_empty_root(artifact_root)
            staged.replace(artifact_root)
            try:
                connection.commit()
            except Exception:
                artifact_root.replace(staged)
                raise


def main(argv: list[str] | None = None) -> int:
    """Run the development fixture loader."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Migrated scratch database URL")
    parser.add_argument(
        "--artifact-root", type=Path, required=True, help="Empty artefact directory"
    )
    args = parser.parse_args(argv)

    try:
        load_seed(args.database_url, args.artifact_root)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    except (OSError, psycopg.Error, tarfile.TarError, zstandard.ZstdError) as exc:
        print(f"Could not restore seed fixture ({type(exc).__name__})", file=sys.stderr)
        return 1
    print("Loaded the RoboProbe small seed fixture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
