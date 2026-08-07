from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from yt_transcripts.db.models import AnalysisRun, Channel, Transcript, Video, VideoAnalysis


def upsert_channel(session: Session, *, youtube_channel_id: str, title: str, url: str) -> Channel:
    channel = get_channel_by_youtube_id(session, youtube_channel_id=youtube_channel_id)
    if channel:
        channel.title = title
        channel.url = url
        return channel
    channel = Channel(youtube_channel_id=youtube_channel_id, title=title, url=url)
    session.add(channel)
    session.flush()
    return channel


def get_channel_by_youtube_id(session: Session, *, youtube_channel_id: str) -> Channel | None:
    return session.scalar(select(Channel).where(Channel.youtube_channel_id == youtube_channel_id))


def list_channels(session: Session) -> list[Channel]:
    return list(session.scalars(select(Channel).order_by(Channel.title.asc())).all())


def upsert_video(session: Session, *, channel_id: int, youtube_video_id: str, title: str, url: str, published_at: datetime | None, duration_seconds: int | None, is_short: bool) -> Video:
    video = get_video_by_youtube_id(session, youtube_video_id=youtube_video_id)
    if video:
        video.channel_id = channel_id
        video.title = title
        video.url = url
        video.published_at = published_at
        video.duration_seconds = duration_seconds
        video.is_short = is_short
        return video
    video = Video(channel_id=channel_id, youtube_video_id=youtube_video_id, title=title, url=url, published_at=published_at, duration_seconds=duration_seconds, is_short=is_short)
    session.add(video)
    session.flush()
    return video


def get_video_by_youtube_id(session: Session, *, youtube_video_id: str) -> Video | None:
    return session.scalar(select(Video).where(Video.youtube_video_id == youtube_video_id))


def list_latest_videos(session: Session, *, limit: int = 50) -> list[Video]:
    return list(session.scalars(select(Video).order_by(Video.published_at.desc()).limit(limit)).all())


def list_unprocessed_videos(session: Session) -> list[Video]:
    stmt = select(Video).where(~Video.id.in_(select(AnalysisRun.video_id))).order_by(Video.published_at.desc())
    return list(session.scalars(stmt).all())


def upsert_transcript(session: Session, *, video_id: int, source: str, language: str | None, raw_transcript_json: dict, normalized_text: str, segment_count: int) -> Transcript:
    transcript = get_transcript_for_video(session, video_id=video_id, source=source, language=language)
    if transcript:
        transcript.raw_transcript_json = raw_transcript_json
        transcript.normalized_text = normalized_text
        transcript.segment_count = segment_count
        transcript.fetched_at = datetime.utcnow()
        return transcript
    transcript = Transcript(video_id=video_id, source=source, language=language, raw_transcript_json=raw_transcript_json, normalized_text=normalized_text, segment_count=segment_count)
    session.add(transcript)
    session.flush()
    return transcript


def get_transcript_for_video(session: Session, *, video_id: int, source: str, language: str | None) -> Transcript | None:
    return session.scalar(select(Transcript).where(Transcript.video_id == video_id, Transcript.source == source, Transcript.language == language))


def list_videos_missing_transcripts(session: Session) -> list[Video]:
    stmt = select(Video).where(~Video.id.in_(select(Transcript.video_id)))
    return list(session.scalars(stmt).all())


def get_existing_analysis_run(session: Session, *, video_id: int, analysis_type: str, model_name: str, prompt_version: str) -> AnalysisRun | None:
    return session.scalar(select(AnalysisRun).where(AnalysisRun.video_id == video_id, AnalysisRun.analysis_type == analysis_type, AnalysisRun.model_name == model_name, AnalysisRun.prompt_version == prompt_version))


def create_analysis_run(session: Session, *, video_id: int, transcript_id: int, analysis_type: str, model_name: str, prompt_version: str, prompt_text: str) -> AnalysisRun:
    run = AnalysisRun(video_id=video_id, transcript_id=transcript_id, analysis_type=analysis_type, model_name=model_name, prompt_version=prompt_version, prompt_text=prompt_text, status="running")
    session.add(run)
    session.flush()
    return run


def complete_analysis_run(session: Session, *, analysis_run: AnalysisRun, raw_response: str, parsed_response_json: dict) -> AnalysisRun:
    analysis_run.raw_response = raw_response
    analysis_run.parsed_response_json = parsed_response_json
    analysis_run.status = "completed"
    analysis_run.error_message = None
    return analysis_run


def fail_analysis_run(session: Session, *, analysis_run: AnalysisRun, error_message: str) -> AnalysisRun:
    analysis_run.status = "failed"
    analysis_run.error_message = error_message
    return analysis_run


def save_video_analysis(session: Session, *, analysis_run_id: int, video_id: int, summary: str | None, main_topics_json: dict | list | None, claims_json: dict | list | None, perspective_json: dict | list | None, sentiment_json: dict | list | None, bias_signals_json: dict | list | None, rhetoric_signals_json: dict | list | None, influence_signals_json: dict | list | None, confidence_score: float | None) -> VideoAnalysis:
    existing = session.scalar(select(VideoAnalysis).where(VideoAnalysis.analysis_run_id == analysis_run_id))
    if existing:
        existing.summary = summary
        existing.main_topics_json = main_topics_json
        existing.claims_json = claims_json
        existing.perspective_json = perspective_json
        existing.sentiment_json = sentiment_json
        existing.bias_signals_json = bias_signals_json
        existing.rhetoric_signals_json = rhetoric_signals_json
        existing.influence_signals_json = influence_signals_json
        existing.confidence_score = confidence_score
        return existing
    row = VideoAnalysis(analysis_run_id=analysis_run_id, video_id=video_id, summary=summary, main_topics_json=main_topics_json, claims_json=claims_json, perspective_json=perspective_json, sentiment_json=sentiment_json, bias_signals_json=bias_signals_json, rhetoric_signals_json=rhetoric_signals_json, influence_signals_json=influence_signals_json, confidence_score=confidence_score)
    session.add(row)
    session.flush()
    return row


def list_videos_missing_analysis(session: Session) -> list[Video]:
    stmt = select(Video).where(~Video.id.in_(select(VideoAnalysis.video_id)))
    return list(session.scalars(stmt).all())
