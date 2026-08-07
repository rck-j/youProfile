from __future__ import annotations

import argparse
import base64
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from yt_transcripts.db.session import _normalized_database_url, get_engine

# Edit this SQL as needed. Keep it as a read-only SELECT/WITH query because the
# utility exports rows and does not manage data mutations.
QUERY = """
SELECT topic, video_id, summary
FROM video_analysis;
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the script-defined database query and export the results to JSON."
    )
    parser.add_argument(
        "--output",
        default="query_results.json",
        help="Path for the JSON output file. Defaults to query_results.json.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation level. Defaults to 2.",
    )
    return parser


def _ensure_read_only_query(query: str) -> str:
    stripped_query = query.strip().rstrip(";")
    if not stripped_query:
        raise ValueError("QUERY must not be empty.")

    first_word = stripped_query.split(maxsplit=1)[0].lower()
    if first_word not in {"select", "with"}:
        raise ValueError("QUERY must be a read-only SELECT or WITH statement.")

    return stripped_query


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return str(value)


def fetch_query_rows(query: str) -> list[dict[str, Any]]:
    engine = get_engine(database_url=_normalized_database_url())
    read_only_query = _ensure_read_only_query(query)

    with engine.connect() as connection:
        result = connection.execute(text(read_only_query))
        return [
            {column: _json_safe(value) for column, value in row.items()}
            for row in result.mappings()
        ]


def write_json(rows: list[dict[str, Any]], output_path: Path, indent: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(rows, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    args = build_parser().parse_args()
    output_path = Path(args.output)
    rows = fetch_query_rows(QUERY)
    write_json(rows, output_path, args.indent)
    print(json.dumps({"status": "ok", "row_count": len(rows), "output": str(output_path)}, indent=2))


if __name__ == "__main__":
    main()
