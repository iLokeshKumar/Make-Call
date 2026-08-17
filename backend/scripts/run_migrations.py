"""
Idempotent production schema migration runner.

Usage
-----
    # Dry-run (print what would run, touch nothing)
    python backend/scripts/run_migrations.py --dry-run

    # Apply pending migrations
    python backend/scripts/run_migrations.py

    # Apply and stop at a specific version
    python backend/scripts/run_migrations.py --target v0004

How it works
------------
1. Connects using the same DATABASE_URL as the application.
2. Creates a `_schema_migrations` audit table if it does not already exist.
3. Scans `backend/migrations/` for SQL files named `v0001_*.sql`, `v0002_*.sql`, …
4. Skips files whose version is already recorded in `_schema_migrations`.
5. Wraps each file in a transaction; rolls back and aborts on any error.
6. Writes a row to `_schema_migrations` after each successful file.

This means running the script twice is completely safe — the second run is a no-op.

Adding a new migration
----------------------
Create `backend/migrations/v0005_<description>.sql` and run the script.
The file must be a valid PostgreSQL script.  It may contain multiple statements
separated by semicolons.  Do NOT use `\\copy` or other psql meta-commands.

Rollback
--------
Automatic rollback happens on error within a migration file.  There is no
automatic rollback of *already-applied* migrations.  If you need to undo a
previous migration, write a new `vNNNN_rollback_<description>.sql` file.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("migrate")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
_AUDIT_TABLE = "_schema_migrations"
_FILENAME_RE = re.compile(r"^(v\d+)_.*\.sql$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_dsn() -> str:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Export it before running this script, e.g.:\n"
            "  export DATABASE_URL=postgresql://user:pass@host:5432/dbname"
        )
    # SQLAlchemy uses `postgresql+psycopg2://…`; strip the driver prefix.
    return dsn.replace("postgresql+psycopg2://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")


def _ensure_audit_table(cur) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_AUDIT_TABLE} (
            id           SERIAL PRIMARY KEY,
            version      TEXT        NOT NULL UNIQUE,
            filename     TEXT        NOT NULL,
            applied_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            duration_ms  INTEGER,
            checksum     TEXT
        );
        """
    )


def _applied_versions(cur) -> set[str]:
    cur.execute(f"SELECT version FROM {_AUDIT_TABLE}")
    return {row[0] for row in cur.fetchall()}


def _migration_files() -> list[tuple[str, Path]]:
    """Return sorted list of (version, path) tuples for all migration files."""
    if not _MIGRATIONS_DIR.exists():
        logger.warning("Migrations directory not found: %s", _MIGRATIONS_DIR)
        return []

    files: list[tuple[str, Path]] = []
    for f in _MIGRATIONS_DIR.iterdir():
        m = _FILENAME_RE.match(f.name)
        if m:
            files.append((m.group(1).lower(), f))

    files.sort(key=lambda x: x[0])
    return files


def _file_checksum(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

def run_migrations(
    dry_run: bool = False,
    target_version: str | None = None,
) -> dict:
    """
    Apply pending migrations.  Returns a summary dict::

        {
            "applied": ["v0001", "v0002"],
            "skipped": ["v0003"],
            "failed":  None,          # or "v0004" if something went wrong
            "dry_run": False,
        }
    """
    dsn = _get_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = False  # we manage transactions manually

    applied_list: list[str] = []
    skipped_list: list[str] = []
    failed_version: str | None = None

    try:
        with conn.cursor() as cur:
            if not dry_run:
                _ensure_audit_table(cur)
                conn.commit()

            already_applied = _applied_versions(cur) if not dry_run else set()
            files = _migration_files()

            if not files:
                logger.info("No migration files found in %s", _MIGRATIONS_DIR)
                return {"applied": [], "skipped": [], "failed": None, "dry_run": dry_run}

            for version, path in files:
                if target_version and version > target_version.lower():
                    logger.info("Stopping at target version %s", target_version)
                    break

                if version in already_applied:
                    logger.info("SKIP  %s  (already applied)", path.name)
                    skipped_list.append(version)
                    continue

                sql = path.read_text(encoding="utf-8")
                checksum = _file_checksum(path)

                if dry_run:
                    logger.info("DRY   %s  would apply (%d bytes)", path.name, len(sql))
                    applied_list.append(version)
                    continue

                logger.info("APPLY %s …", path.name)
                start_ts = datetime.now(timezone.utc)

                try:
                    cur.execute(sql)
                    duration_ms = int(
                        (datetime.now(timezone.utc) - start_ts).total_seconds() * 1000
                    )
                    cur.execute(
                        f"""
                        INSERT INTO {_AUDIT_TABLE} (version, filename, applied_at, duration_ms, checksum)
                        VALUES (%s, %s, NOW(), %s, %s)
                        """,
                        (version, path.name, duration_ms, checksum),
                    )
                    conn.commit()
                    logger.info("      ✓ %s applied in %d ms", version, duration_ms)
                    applied_list.append(version)

                except Exception as exc:
                    conn.rollback()
                    failed_version = version
                    logger.error(
                        "FAILED  %s: %s  —  rolled back, stopping.",
                        path.name,
                        exc,
                    )
                    break

    finally:
        conn.close()

    return {
        "applied": applied_list,
        "skipped": skipped_list,
        "failed": failed_version,
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Idempotent production schema migration runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be applied without touching the database",
    )
    parser.add_argument(
        "--target",
        metavar="VERSION",
        default=None,
        help="Stop after applying this version (e.g. v0004)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    summary = run_migrations(dry_run=args.dry_run, target_version=args.target)

    print("\n─── Migration summary ───")
    print(f"  Dry-run  : {summary['dry_run']}")
    print(f"  Applied  : {summary['applied'] or '(none)'}")
    print(f"  Skipped  : {summary['skipped'] or '(none)'}")
    print(f"  Failed   : {summary['failed'] or '(none)'}")

    if summary["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
