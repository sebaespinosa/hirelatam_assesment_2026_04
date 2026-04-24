from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.db import get_connection
from src.db.init import init_db


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()
