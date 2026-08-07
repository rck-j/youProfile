from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "reprocess_transcripts_with_prompt.py"
SPEC = importlib.util.spec_from_file_location("reprocess_transcripts_with_prompt", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
reprocess_transcripts_with_prompt = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = reprocess_transcripts_with_prompt
SPEC.loader.exec_module(reprocess_transcripts_with_prompt)


class FakeResponses:
    def __init__(self) -> None:
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)

        class FakeResponse:
            output_text = '{"summary":"summary text","topics":[{"topic":"policy"}],"confidence":0.8}'

        return FakeResponse()


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


def test_load_prompt_accepts_literal_prompt_text() -> None:
    prompt = reprocess_transcripts_with_prompt.load_prompt(prompt_text="  Extract topics.  ")

    assert prompt == "Extract topics."


def test_load_transcript_records_supports_json_and_jsonl_formats(tmp_path: Path) -> None:
    (tmp_path / "video.json").write_text(
        json.dumps(
            {
                "video": {"video_id": "abc123", "channel_id": "channel-1", "channel_title": "Channel", "title": "Video"},
                "transcript": {"transcript_text": "Nested transcript"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "records.jsonl").write_text(
        json.dumps({"video_id": "def456", "channel_title": "JSONL Channel", "transcript_text": "Line transcript"})
        + "\n"
        + json.dumps({"video_id": "skipped", "transcript_available": False, "transcript_text": "Skip me"})
        + "\n",
        encoding="utf-8",
    )

    records, skipped = reprocess_transcripts_with_prompt.load_transcript_records(tmp_path)

    assert [record.video_id for record in records] == ["def456", "abc123"]
    assert [record.transcript_text for record in records] == ["Line transcript", "Nested transcript"]
    assert skipped == [
        {"file": str(tmp_path / "records.jsonl"), "record_index": 1, "reason": "missing_transcript_text"}
    ]


def test_reprocess_transcripts_sends_prompt_and_writes_mapped_fields(tmp_path: Path) -> None:
    (tmp_path / "video.json").write_text(
        json.dumps(
            {
                "video": {"video_id": "abc123", "channel_id": "channel-1", "channel_title": "Channel"},
                "transcript": {"transcript_text": "Transcript body"},
            }
        ),
        encoding="utf-8",
    )
    fake_openai = FakeOpenAIClient()
    client = reprocess_transcripts_with_prompt.PromptExtractionClient(client=fake_openai)

    payload = reprocess_transcripts_with_prompt.reprocess_transcripts(
        input_dir=tmp_path,
        prompt="Extract structured topics.",
        model="gpt-test",
        client=client,
    )

    assert payload["processed_count"] == 1
    assert payload["results"][0]["mapped_fields"]["summary"] == "summary text"
    assert payload["results"][0]["mapped_fields"]["main_topics"] == [{"topic": "policy"}]
    request = fake_openai.responses.requests[0]
    assert request["model"] == "gpt-test"
    assert request["input"][0]["content"][0]["text"] == "Extract structured topics."
    assert "Transcript body" in request["input"][1]["content"][0]["text"]
