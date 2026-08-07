from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "analyze_query_results_with_openai.py"
SPEC = importlib.util.spec_from_file_location("analyze_query_results_with_openai", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
analyze_query_results_with_openai = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analyze_query_results_with_openai)


class FakeResponses:
    def __init__(self) -> None:
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs

        class FakeResponse:
            output_text = "  concise analysis  "

        return FakeResponse()


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


def test_load_prompt_resolves_prompt_directory_file() -> None:
    prompt = analyze_query_results_with_openai.load_prompt("query_results_analysis_prompt.txt")

    assert "YouTube Intelligence Pipeline" in prompt


def test_build_query_payload_includes_query_metadata_and_rows() -> None:
    payload = json.loads(
        analyze_query_results_with_openai.build_query_payload(
            "SELECT id FROM sample;",
            [{"id": 1}],
        )
    )

    assert payload == {"query": "SELECT id FROM sample", "row_count": 1, "rows": [{"id": 1}]}


def test_analyze_query_results_sends_prompt_and_query_payload_to_openai() -> None:
    client = FakeOpenAIClient()

    output_text = analyze_query_results_with_openai.analyze_query_results(
        prompt="Prompt instructions",
        rows=[{"topic": "testing"}],
        query="SELECT topic FROM sample",
        model="gpt-test",
        client=client,
    )

    assert output_text == "concise analysis"
    request = client.responses.request
    assert request["model"] == "gpt-test"
    assert request["input"][0]["content"][0]["text"] == "Prompt instructions"
    user_text = request["input"][1]["content"][0]["text"]
    assert "Analyze these database query results" in user_text
    assert '"row_count": 1' in user_text
    assert '"topic": "testing"' in user_text


def test_build_output_payload_omits_raw_rows_but_includes_metadata() -> None:
    payload = analyze_query_results_with_openai.build_output_payload(
        model="gpt-test",
        prompt_file="prompt.txt",
        output_text="analysis",
        query="SELECT id FROM sample;",
        rows=[{"id": 1}],
    )

    assert payload == {
        "status": "ok",
        "model": "gpt-test",
        "prompt_file": "prompt.txt",
        "query": "SELECT id FROM sample",
        "row_count": 1,
        "analysis": "analysis",
    }


def test_write_json_creates_parent_directory(tmp_path) -> None:
    output_path = tmp_path / "nested" / "analysis.json"

    analyze_query_results_with_openai.write_json({"analysis": "ok"}, output_path, indent=2)

    assert json.loads(output_path.read_text(encoding="utf-8")) == {"analysis": "ok"}
