from __future__ import annotations

from yt_transcripts.services.transcript_intelligence_pipeline import TranscriptIntelligencePipeline


def test_map_analysis_fields_supports_nested_analysis_payload() -> None:
    payload = {
        "analysis": {
            "summary": "summary text",
            "topics": [{"topic": "energy"}],
            "key_claims": [{"claim": "c1"}],
            "perspectives": [{"stance": "s1"}],
            "sentiment_analysis": {"tone": "neutral"},
            "bias": {"loaded_language": True},
            "rhetorical_signals": [{"signal": "fear appeal"}],
            "influence": [{"signal": "authority"}],
            "confidence": 0.87,
        }
    }

    mapped = TranscriptIntelligencePipeline._map_analysis_fields(
        TranscriptIntelligencePipeline._normalize_analysis_payload(payload)
    )

    assert mapped["summary"] == "summary text"
    assert mapped["main_topics"] == [{"topic": "energy"}]
    assert mapped["claims"] == [{"claim": "c1"}]
    assert mapped["perspective"] == [{"stance": "s1"}]
    assert mapped["sentiment"] == {"tone": "neutral"}
    assert mapped["bias_signals"] == {"loaded_language": True}
    assert mapped["rhetoric_signals"] == [{"signal": "fear appeal"}]
    assert mapped["influence_signals"] == [{"signal": "authority"}]
    assert mapped["confidence_score"] == 0.87



def test_map_analysis_fields_supports_main_topics_wrapper_payload() -> None:
    payload = {
        "main_topics": {
            "summary": "summary text",
            "topics": [{"topic": "energy"}],
            "key_claims": [{"claim": "c1"}],
            "perspectives": [{"stance": "s1"}],
            "sentiment_analysis": {"tone": "neutral"},
            "bias": {"loaded_language": True},
            "rhetorical_signals": [{"signal": "fear appeal"}],
            "influence": [{"signal": "authority"}],
            "confidence": 0.87,
        }
    }

    mapped = TranscriptIntelligencePipeline._map_analysis_fields(
        TranscriptIntelligencePipeline._normalize_analysis_payload(payload)
    )

    assert mapped["summary"] == "summary text"
    assert mapped["main_topics"] == [{"topic": "energy"}]
    assert mapped["claims"] == [{"claim": "c1"}]
    assert mapped["perspective"] == [{"stance": "s1"}]
    assert mapped["sentiment"] == {"tone": "neutral"}
    assert mapped["bias_signals"] == {"loaded_language": True}
    assert mapped["rhetoric_signals"] == [{"signal": "fear appeal"}]
    assert mapped["influence_signals"] == [{"signal": "authority"}]
    assert mapped["confidence_score"] == 0.87


def test_normalize_and_map_unwraps_alias_wrappers() -> None:
    payload = {"result": {"data": {"overall_summary": "sum", "topics": [{"topic": "macro"}], "key_claims": [{"claim": "c"}]}}}
    normalized = TranscriptIntelligencePipeline._normalize_analysis_payload(payload)
    mapped = TranscriptIntelligencePipeline._map_analysis_fields(normalized)
    assert normalized["overall_summary"] == "sum"
    assert mapped["summary"] == "sum"
    assert mapped["main_topics"] == [{"topic": "macro"}]
    assert mapped["claims"] == [{"claim": "c"}]


def test_normalize_and_map_supports_json_string_payload() -> None:
    payload = '{"analysis":{"summary":"s","topics":[{"topic":"t1"}],"confidence":0.2}}'
    mapped = TranscriptIntelligencePipeline._map_analysis_fields(
        TranscriptIntelligencePipeline._normalize_analysis_payload(payload)
    )
    assert mapped["summary"] == "s"
    assert mapped["main_topics"] == [{"topic": "t1"}]
    assert mapped["confidence_score"] == 0.2


def test_normalize_and_map_supports_markdown_fenced_json_payload() -> None:
    payload = """```json
{"analysis":{"summary":"fenced","topics":[{"topic":"t1"}]}}
```"""
    mapped = TranscriptIntelligencePipeline._map_analysis_fields(
        TranscriptIntelligencePipeline._normalize_analysis_payload(payload)
    )
    assert mapped["summary"] == "fenced"
    assert mapped["main_topics"] == [{"topic": "t1"}]


def test_normalize_and_map_returns_empty_for_malformed_payload() -> None:
    mapped = TranscriptIntelligencePipeline._map_analysis_fields(
        TranscriptIntelligencePipeline._normalize_analysis_payload("```json\n{invalid}\n```")
    )
    assert mapped == {}
