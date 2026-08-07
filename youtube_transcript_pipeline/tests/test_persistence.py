from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from yt_transcripts.db.models import AnalysisRun, Base, Channel, Transcript, Video, VideoAnalysis
from yt_transcripts.repositories.persistence import (
    complete_analysis_run,
    create_analysis_run,
    get_existing_analysis_run,
    save_video_analysis,
    upsert_channel,
    upsert_transcript,
    upsert_video,
)


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
    channel = upsert_channel(session, youtube_channel_id="chan1", title="C1", url="u1")
    channel2 = upsert_channel(session, youtube_channel_id="chan1", title="C2", url="u2")
    assert channel.id == channel2.id
    assert channel2.title == "C2"

    video = upsert_video(
        session,
        channel_id=channel.id,
        youtube_video_id="vid1",
        title="V1",
        url="vu1",
        published_at=datetime.utcnow(),
        duration_seconds=120,
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
        is_short=True,
    )
    assert video.id == video2.id
    assert video2.title == "V2"

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
    channel = upsert_channel(session, youtube_channel_id="chan1", title="C1", url="u1")
    video = upsert_video(session, channel_id=channel.id, youtube_video_id="vid1", title="V1", url="vu1", published_at=None, duration_seconds=10, is_short=True)
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
