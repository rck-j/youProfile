from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from openai import OpenAI
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
for import_path in (SRC_PATH, SCRIPT_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from yt_transcripts.db.session import _normalized_database_url, get_engine

from export_query_to_json import _ensure_read_only_query, _json_safe

# Edit this SQL as needed. Keep it as a read-only SELECT/WITH query because the
# utility sends rows to OpenAI and does not manage data mutations.
QUERY = """
SELECT topic, video_id, summary
FROM video_analysis;
"""

DEFAULT_PROMPT_FILE = PROJECT_ROOT / "prompts" / "query_results_analysis_prompt.txt"
DEFAULT_OUTPUT_FILE = PROJECT_ROOT / "outputs" / "query_results_analysis.json"
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the script-defined database query, send the JSON rows to OpenAI "
            "with a prompt file, and write the model output to a file."
        )
    )
    parser.add_argument(
        "--prompt-file",
        default=str(DEFAULT_PROMPT_FILE),
        help=f"Prompt file path. Defaults to {DEFAULT_PROMPT_FILE}.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_FILE),
        help=f"Path for the JSON output file. Defaults to {DEFAULT_OUTPUT_FILE}.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="OpenAI model to use. Defaults to OPENAI_MODEL or gpt-5.",
    )
    parser.add_argument(
        "--input-file",
        action="append",
        default=[],
        help=(
            "Local file to upload to OpenAI with purpose=user_data and attach to "
            "the Responses API request for processing. Can be supplied multiple times."
        ),
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation level for the output file. Defaults to 2.",
    )
    return parser


def fetch_query_rows(query: str) -> list[dict[str, Any]]:
    engine = get_engine(database_url=_normalized_database_url())
    read_only_query = _ensure_read_only_query(query)

    with engine.connect() as connection:
        result = connection.execute(text(read_only_query))
        return [
            {column: _json_safe(value) for column, value in row.items()}
            for row in result.mappings()
        ]


def load_prompt(prompt_file: str | Path) -> str:
    prompt_path = Path(prompt_file)
    if not prompt_path.is_absolute() and not prompt_path.exists():
        prompt_path = PROJECT_ROOT / "prompts" / prompt_path

    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(f"Prompt file is empty: {prompt_path}")
    return prompt


def build_query_payload(query: str, rows: list[dict[str, Any]]) -> str:
    payload = {
        "query": _ensure_read_only_query(query),
        "row_count": len(rows),
        "rows": rows,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def resolve_input_file(input_file: str | Path) -> Path:
    input_path = Path(input_file).expanduser()
    if not input_path.is_absolute() and not input_path.exists():
        input_path = PROJECT_ROOT / input_path

    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")
    if not input_path.is_file():
        raise ValueError(f"Input path is not a file: {input_path}")
    return input_path


def upload_file_for_processing(
    *,
    client: OpenAI,
    input_file: str | Path,
) -> dict[str, Any]:
    input_path = resolve_input_file(input_file)
    with input_path.open("rb") as file_handle:
        uploaded_file = client.files.create(file=file_handle, purpose="user_data")

    return {
        "file_id": uploaded_file.id,
        "filename": getattr(uploaded_file, "filename", input_path.name),
        "path": str(input_path),
        "bytes": getattr(uploaded_file, "bytes", input_path.stat().st_size),
        "purpose": getattr(uploaded_file, "purpose", "user_data"),
    }


def upload_files_for_processing(
    *,
    client: OpenAI,
    input_files: Sequence[str | Path],
) -> list[dict[str, Any]]:
    return [
        upload_file_for_processing(client=client, input_file=input_file)
        for input_file in input_files
    ]


def build_user_content(
    *,
    query: str,
    rows: list[dict[str, Any]],
    uploaded_files: Sequence[dict[str, Any]] = (),
) -> list[dict[str, str]]:
    content = [
        {
            "type": "input_text",
            "text": "Analyze these database query results:\n"
            + build_query_payload(query, rows),
        }
    ]
    content.extend(
        {
            "type": "input_file",
            "file_id": uploaded_file["file_id"],
        }
        for uploaded_file in uploaded_files
    )
    return content


def analyze_query_results(
    *,
    prompt: str,
    rows: list[dict[str, Any]],
    query: str,
    model: str,
    client: OpenAI | None = None,
    uploaded_files: Sequence[dict[str, Any]] = (),
) -> str:
    openai_client = client or OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = openai_client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
            {
                "role": "user",
                "content": build_user_content(
                    query=query, rows=rows, uploaded_files=uploaded_files
                ),
            },
        ],
    )
    return response.output_text.strip()


def build_output_payload(
    *,
    model: str,
    prompt_file: str | Path,
    output_text: str,
    query: str,
    rows: list[dict[str, Any]],
    uploaded_files: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    payload = {
        "status": "ok",
        "model": model,
        "prompt_file": str(prompt_file),
        "query": _ensure_read_only_query(query),
        "row_count": len(rows),
        "analysis": output_text,
    }
    if uploaded_files:
        payload["uploaded_files"] = list(uploaded_files)
    return payload


def write_json(payload: dict[str, Any], output_path: Path, indent: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main() -> None:
    args = build_parser().parse_args()
    prompt = load_prompt(args.prompt_file)
    rows = fetch_query_rows(QUERY)
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    uploaded_files = upload_files_for_processing(
        client=openai_client, input_files=args.input_file
    )
    output_text = analyze_query_results(
        prompt=prompt,
        rows=rows,
        query=QUERY,
        model=args.model,
        client=openai_client,
        uploaded_files=uploaded_files,
    )
    output_payload = build_output_payload(
        model=args.model,
        prompt_file=args.prompt_file,
        output_text=output_text,
        query=QUERY,
        rows=rows,
        uploaded_files=uploaded_files,
    )
    output_path = Path(args.output)
    write_json(output_payload, output_path, args.indent)
    print(
        json.dumps(
            {"status": "ok", "row_count": len(rows), "output": str(output_path)},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
