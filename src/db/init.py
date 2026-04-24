"""Drop and recreate the SQLite database from schema.sql.

Usage:
    python -m src.db.init                # wipes data/db.sqlite and replays schema
    python -m src.db.init --keep         # keeps existing file, applies schema idempotently
    python -m src.db.init --db-path /tmp/foo.sqlite
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from src.db import DEFAULT_DB_PATH

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def init_db(db_path: Path, *, drop: bool = True) -> None:
    if drop and db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text()
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize the SQLite database.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Apply schema without dropping the existing database.",
    )
    args = parser.parse_args()
    init_db(args.db_path, drop=not args.keep)
    action = "applied schema to" if args.keep else "initialized"
    print(f"{action} {args.db_path}")


if __name__ == "__main__":
    main()
