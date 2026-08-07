from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "export_query_to_json.py"
SPEC = importlib.util.spec_from_file_location("export_query_to_json", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
export_query_to_json = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export_query_to_json)


def test_fetch_query_rows_uses_database_url_and_returns_json_safe_rows(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "export.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_engine(database_url, future=True)

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT, created_at TEXT)"))
        connection.execute(
            text("INSERT INTO sample (id, name, created_at) VALUES (1, 'alpha', '2026-05-18T00:00:00')")
        )

    monkeypatch.setenv("DATABASE_URL", database_url)

    rows = export_query_to_json.fetch_query_rows("SELECT id, name, created_at FROM sample")

    assert rows == [{"id": 1, "name": "alpha", "created_at": "2026-05-18T00:00:00"}]


def test_write_json_creates_parent_directory(tmp_path) -> None:
    output_path = tmp_path / "nested" / "rows.json"

    export_query_to_json.write_json([{"id": 1}], output_path, indent=2)

    assert json.loads(output_path.read_text(encoding="utf-8")) == [{"id": 1}]


def test_json_safe_converts_common_database_values() -> None:
    payload = {
        "timestamp": datetime(2026, 5, 18, 12, 30),
        "amount": Decimal("3.14"),
        "binary": b"abc",
    }

    assert export_query_to_json._json_safe(payload) == {
        "timestamp": "2026-05-18T12:30:00",
        "amount": 3.14,
        "binary": "YWJj",
    }


def test_fetch_query_rows_rejects_mutation_queries() -> None:
    try:
        export_query_to_json.fetch_query_rows("DELETE FROM sample")
    except ValueError as exc:
        assert "read-only SELECT or WITH" in str(exc)
    else:
        raise AssertionError("Expected mutation query to be rejected")
