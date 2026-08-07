from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from yt_transcripts.clients.openai_analysis_client import OpenAIAnalysisClient
from yt_transcripts.services.prompt_service import PromptService
from yt_transcripts.services.transcript_intelligence_pipeline import TranscriptIntelligencePipeline

DEFAULT_MODEL = os.getenv("OPENAI_ANALYSIS_MODEL", os.getenv("OPENAI_MODEL", "gpt-5"))
DEFAULT_OUTPUT_FILE = PROJECT_ROOT / "outputs" / "prompt_extraction_results.json"
SKIPPED_OUTPUT_FILES = {
    "batch_summary.json",
    "topic_perspectives_aggregate.json",
    "prompt_extraction_results.json",
}


@dataclass(frozen=True)
class TranscriptRecord:
    video_id: str
    transcript_text: str
    source_file: str
    channel_id: str | None = None
    channel_title: str | None = None
    title: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "channel_id": self.channel_id,
            "channel_title": self.channel_title,
            "title": self.title,
            "source_file": self.source_file,
        }


class PromptExtractionClient:
    """Runs an extraction prompt against saved transcript text."""

    def __init__(self, client: OpenAI | None = None) -> None:
        self._client = client or OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def extract(
        self,
        *,
        model: str,
        prompt: str,
        record: TranscriptRecord,
    ) -> dict[str, Any]:
        user_prompt = (
            "Run the extraction instructions against this saved YouTube transcript. "
            "Return only the requested output format.\n"
            f"video_id: {record.video_id}\n"
            f"channel_id: {record.channel_id or ''}\n"
            f"channel_title: {record.channel_title or ''}\n"
            f"title: {record.title or ''}\n"
            f"source_file: {record.source_file}\n\n"
            f"transcript:\n{record.transcript_text}"
        )
        response = self._client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
            ],
        )
        response_text = response.output_text.strip()
        parsed_response = OpenAIAnalysisClient._parse_json(response_text)
        if parsed_response == {"topics": []} and response_text:
            return {"raw_text": response_text}
        return parsed_response


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reprocess saved transcript result files with a supplied extraction prompt "
            "so prompt outputs can be compared without refetching videos."
        )
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Directory containing transcript result .json or .jsonl files.",
    )
    parser.add_argument(
        "--prompt-file",
        default="",
        help="Prompt file path. Relative names are resolved from the prompts/ directory.",
    )
    parser.add_argument(
        "--prompt-text",
        default="",
        help="Literal prompt text. Use this instead of --prompt-file for one-off prompt tests.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="OpenAI model to use. Defaults to OPENAI_ANALYSIS_MODEL, OPENAI_MODEL, or gpt-5.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_FILE),
        help=f"Path for the JSON comparison artifact. Defaults to {DEFAULT_OUTPUT_FILE}.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search input directory recursively for .json and .jsonl files.",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=0,
        help="Optional maximum number of transcript records to process. 0 means no limit.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation level for output. Defaults to 2.",
    )
    return parser


def load_prompt(*, prompt_file: str = "", prompt_text: str = "") -> str:
    if bool(prompt_file) == bool(prompt_text):
        raise ValueError("Pass exactly one of --prompt-file or --prompt-text.")

    prompt = prompt_text.strip() if prompt_text else PromptService().load_prompt(prompt_file)
    if not prompt:
        raise ValueError("Prompt is empty.")
    return prompt


def iter_transcript_files(input_dir: str | Path, *, recursive: bool = False) -> Iterable[Path]:
    root = Path(input_dir)
    if not root.exists():
        raise FileNotFoundError(f"Input directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {root}")

    globber = root.rglob if recursive else root.glob
    files = [*globber("*.json"), *globber("*.jsonl")]
    for file_path in sorted(files):
        if file_path.name in SKIPPED_OUTPUT_FILES:
            continue
        yield file_path


def load_transcript_records(input_dir: str | Path, *, recursive: bool = False) -> tuple[list[TranscriptRecord], list[dict[str, Any]]]:
    records: list[TranscriptRecord] = []
    skipped: list[dict[str, Any]] = []

    for file_path in iter_transcript_files(input_dir, recursive=recursive):
        try:
            payloads = _load_payloads(file_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            skipped.append({"file": str(file_path), "reason": "invalid_json", "error": str(exc)})
            continue

        for index, payload in enumerate(payloads):
            record = _record_from_payload(payload, source_file=str(file_path), index=index)
            if record is None:
                skipped.append({"file": str(file_path), "record_index": index, "reason": "missing_transcript_text"})
                continue
            records.append(record)

    return records, skipped


def _load_payloads(file_path: Path) -> list[dict[str, Any]]:
    if file_path.suffix == ".jsonl":
        payloads: list[dict[str, Any]] = []
        for line_number, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if isinstance(payload, dict):
                payloads.append(payload)
            else:
                raise ValueError(f"JSONL line {line_number} is not an object")
        return payloads

    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _record_from_payload(payload: dict[str, Any], *, source_file: str, index: int) -> TranscriptRecord | None:
    transcript = payload.get("transcript") if isinstance(payload.get("transcript"), dict) else {}
    video = payload.get("video") if isinstance(payload.get("video"), dict) else {}

    if transcript.get("no_transcript") or payload.get("transcript_available") is False:
        return None

    transcript_text = _first_text(
        transcript.get("transcript_text"),
        transcript.get("text"),
        transcript.get("raw_text"),
        transcript.get("processed_text"),
        payload.get("transcript_text"),
        payload.get("text"),
        payload.get("raw_text"),
        payload.get("processed_text"),
    )
    if not transcript_text:
        return None

    video_id = str(video.get("video_id") or payload.get("video_id") or payload.get("youtube_video_id") or Path(source_file).stem)
    if index and video_id == Path(source_file).stem:
        video_id = f"{video_id}-{index + 1}"

    return TranscriptRecord(
        video_id=video_id,
        channel_id=_optional_text(video.get("channel_id") or payload.get("channel_id")),
        channel_title=_optional_text(video.get("channel_title") or payload.get("channel_title")),
        title=_optional_text(video.get("title") or payload.get("title")),
        transcript_text=transcript_text,
        source_file=source_file,
    )


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def reprocess_transcripts(
    *,
    input_dir: str | Path,
    prompt: str,
    model: str,
    recursive: bool = False,
    max_records: int = 0,
    client: PromptExtractionClient | None = None,
) -> dict[str, Any]:
    records, skipped = load_transcript_records(input_dir, recursive=recursive)
    records_found = len(records)
    if max_records > 0:
        skipped.extend(
            {"video_id": record.video_id, "source_file": record.source_file, "reason": "max_records_limit"}
            for record in records[max_records:]
        )
        records = records[:max_records]

    extraction_client = client or PromptExtractionClient()
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for record in records:
        try:
            extraction = extraction_client.extract(model=model, prompt=prompt, record=record)
        except Exception as exc:
            errors.append({**record.to_metadata(), "status": "failed", "error": str(exc)})
            continue

        normalized = TranscriptIntelligencePipeline._normalize_analysis_payload(extraction)
        mapped = TranscriptIntelligencePipeline._map_analysis_fields(normalized)
        results.append(
            {
                **record.to_metadata(),
                "status": "ok",
                "extraction": extraction,
                "normalized_extraction": normalized,
                "mapped_fields": mapped,
            }
        )

    return {
        "status": "ok" if not errors else "partial_failure",
        "model": model,
        "input_dir": str(Path(input_dir).resolve()),
        "records_found": records_found,
        "processed_count": len(results),
        "error_count": len(errors),
        "skipped_count": len(skipped),
        "results": results,
        "errors": errors,
        "skipped": skipped,
    }


def write_json(payload: dict[str, Any], output_path: str | Path, indent: int = 2) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    args = build_parser().parse_args()
    prompt = load_prompt(prompt_file=args.prompt_file, prompt_text=args.prompt_text)
    payload = reprocess_transcripts(
        input_dir=args.input_dir,
        prompt=prompt,
        model=args.model,
        recursive=args.recursive,
        max_records=args.max_records,
    )
    write_json(payload, args.output, args.indent)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "processed_count": payload["processed_count"],
                "error_count": payload["error_count"],
                "skipped_count": payload["skipped_count"],
                "output": str(Path(args.output)),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
