from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from yt_transcripts.db.models import AnalysisRun, Base, Channel, Transcript, Video, VideoAnalysis, VideoAnalysisTopic
from yt_transcripts.repositories.persistence import (
    complete_analysis_run,
    create_analysis_run,
    get_existing_analysis_run,
    save_video_analysis,
    save_video_analysis_topics,
    upsert_channel,
    upsert_transcript,
    upsert_video,
)
from yt_transcripts.services.transcript_intelligence_pipeline import TranscriptIntelligencePipeline


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    return SessionLocal()


def test_database_initialization() -> None:
    session = make_session()
    assert session.scalar(select(Channel)) is None


def test_channel_video_transcript_upserts_and_duplicate_prevention() -> None:
    session = make_session()
    channel = upsert_channel(session, youtube_channel_id="chan1", title="C1", url="u1", subscriber_count=100)
    channel2 = upsert_channel(session, youtube_channel_id="chan1", title="C2", url="u2", subscriber_count=200)
    assert channel.id == channel2.id
    assert channel2.title == "C2"
    assert channel2.subscriber_count == 200

    video = upsert_video(
        session,
        channel_id=channel.id,
        youtube_video_id="vid1",
        title="V1",
        url="vu1",
        published_at=datetime.utcnow(),
        duration_seconds=120,
        view_count=1000,
        like_count=100,
        is_short=False,
    )
    video2 = upsert_video(
        session,
        channel_id=channel.id,
        youtube_video_id="vid1",
        title="V2",
        url="vu2",
        published_at=datetime.utcnow(),
        duration_seconds=60,
        view_count=2000,
        like_count=200,
        is_short=True,
    )
    assert video.id == video2.id
    assert video2.title == "V2"
    assert video2.view_count == 2000
    assert video2.like_count == 200

    t1 = upsert_transcript(
        session,
        video_id=video.id,
        source="api",
        language="en",
        raw_transcript_json={"a": 1},
        normalized_text="text",
        segment_count=1,
    )
    t2 = upsert_transcript(
        session,
        video_id=video.id,
        source="api",
        language="en",
        raw_transcript_json={"a": 2},
        normalized_text="text2",
        segment_count=2,
    )
    assert t1.id == t2.id
    assert t2.segment_count == 2


def test_analysis_run_uniqueness_and_video_analysis_save() -> None:
    session = make_session()
    channel = upsert_channel(session, youtube_channel_id="chan1", title="C1", url="u1", subscriber_count=1000)
    video = upsert_video(session, channel_id=channel.id, youtube_video_id="vid1", title="V1", url="vu1", published_at=None, duration_seconds=10, view_count=10, like_count=1, is_short=True)
    transcript = upsert_transcript(session, video_id=video.id, source="api", language="en", raw_transcript_json={}, normalized_text="abc", segment_count=0)

    run = create_analysis_run(session, video_id=video.id, transcript_id=transcript.id, analysis_type="topic_perspective", model_name="gpt", prompt_version="v1", prompt_text="prompt")
    existing = get_existing_analysis_run(session, video_id=video.id, analysis_type="topic_perspective", model_name="gpt", prompt_version="v1")
    assert existing and existing.id == run.id

    complete_analysis_run(session, analysis_run=run, raw_response="{}", parsed_response_json={"summary": "s"})
    va = save_video_analysis(
        session,
        analysis_run_id=run.id,
        video_id=video.id,
        summary="sum",
        main_topics_json=["t1"],
        claims_json=[],
        perspective_json={},
        sentiment_json={},
        bias_signals_json={},
        rhetoric_signals_json={},
        influence_signals_json={},
        confidence_score=0.9,
    )
    assert va.summary == "sum"
    assert va.confidence_score == 0.9


def test_video_analysis_split_columns_from_wrapped_payload() -> None:
    session = make_session()
    channel = upsert_channel(session, youtube_channel_id="chan2", title="C2", url="u2")
    video = upsert_video(session, channel_id=channel.id, youtube_video_id="vid2", title="V2", url="vu2", published_at=None, duration_seconds=10, view_count=10, like_count=1, is_short=True)
    transcript = upsert_transcript(session, video_id=video.id, source="api", language="en", raw_transcript_json={}, normalized_text="abc", segment_count=0)
    run = create_analysis_run(session, video_id=video.id, transcript_id=transcript.id, analysis_type="topic_perspective", model_name="gpt", prompt_version="v1", prompt_text="prompt")

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
    va = save_video_analysis(
        session,
        analysis_run_id=run.id,
        video_id=video.id,
        summary=mapped["summary"],
        main_topics_json=mapped["main_topics"],
        claims_json=mapped["claims"],
        perspective_json=mapped["perspective"],
        sentiment_json=mapped["sentiment"],
        bias_signals_json=mapped["bias_signals"],
        rhetoric_signals_json=mapped["rhetoric_signals"],
        influence_signals_json=mapped["influence_signals"],
        confidence_score=mapped["confidence_score"],
    )

    assert va.main_topics_json == [{"topic": "energy"}]
    assert va.claims_json == [{"claim": "c1"}]
    assert va.perspective_json == [{"stance": "s1"}]
    assert va.sentiment_json == {"tone": "neutral"}


def test_save_video_analysis_topics_inserts_multiple_rows() -> None:
    session = make_session()
    inserted = save_video_analysis_topics(
        session,
        analysis_run_id=33,
        video_id=77,
        main_topics_json=[
            {
                "topic": "Defense Leadership",
                "event_title": "Event 1",
                "summary": "s1",
                "entities": ["entity1", "entity2"],
                "time_context": "current",
                "perspective": "p1",
                "analysis": {"framing": "f1", "narrative": "n1", "rhetoric": ["r1"], "influence": "i1"},
            },
            {
                "topic": "Civil-Military Relations",
                "event_title": "Event 2",
                "summary": "s2",
                "entities": ["entity3"],
                "time_context": "historical",
                "perspective": "p2",
                "analysis": {"framing": "f2", "narrative": "n2", "rhetoric": ["r2"], "influence": "i2"},
            },
        ],
    )
    assert inserted == 2
    rows = session.scalars(select(VideoAnalysisTopic).where(VideoAnalysisTopic.analysis_run_id == 33, VideoAnalysisTopic.video_id == 77)).all()
    assert len(rows) == 2
    assert {row.topic for row in rows} == {"Defense Leadership", "Civil-Military Relations"}
    assert {row.event_title for row in rows} == {"Event 1", "Event 2"}
    assert {row.time_context for row in rows} == {"current", "historical"}


def test_save_video_analysis_topics_handles_empty_or_missing_list() -> None:
    session = make_session()
    assert save_video_analysis_topics(session, analysis_run_id=1, video_id=2, main_topics_json=None) == 0
    assert save_video_analysis_topics(session, analysis_run_id=1, video_id=2, main_topics_json={"topic": "x"}) == 0
    rows = session.scalars(select(VideoAnalysisTopic)).all()
    assert rows == []


def test_save_video_analysis_topics_is_idempotent_per_run_and_video() -> None:
    session = make_session()
    first_insert = save_video_analysis_topics(
        session,
        analysis_run_id=9,
        video_id=99,
        main_topics_json=[{"topic": "A", "summary": "s", "perspective": "p", "analysis": {}}],
    )
    second_insert = save_video_analysis_topics(
        session,
        analysis_run_id=9,
        video_id=99,
        main_topics_json=[
            {"topic": "A", "summary": "s-new", "perspective": "p-new", "analysis": {}},
            {"topic": "B", "summary": "s2", "perspective": "p2", "analysis": {}},
        ],
    )
    assert first_insert == 1
    assert second_insert == 2
    rows = session.scalars(select(VideoAnalysisTopic).where(VideoAnalysisTopic.analysis_run_id == 9, VideoAnalysisTopic.video_id == 99)).all()
    assert len(rows) == 2
