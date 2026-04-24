from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(os.environ.get("DB_PATH", "data/db.sqlite"))


def get_connection(
    db_path: Path | str | None = None,
    *,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    """Open a SQLite connection with Row factory and foreign keys enabled.

    Callers are responsible for closing the connection. Pass
    ``check_same_thread=False`` when the connection will be reused across
    Streamlit reruns (each rerun lands on a new thread); safe here because
    the dashboard is read-only and single-user.
    """
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = sqlite3.connect(path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


__all__ = ["DEFAULT_DB_PATH", "get_connection"]
