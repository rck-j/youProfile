from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from yt_transcripts.clients.youtube_data import YouTubeDataClient
from yt_transcripts.config import get_transcript_duration_bounds
from yt_transcripts.db.session import SessionLocal
from yt_transcripts.models.transcript import TranscriptResult
from yt_transcripts.models.video import VideoItem
from yt_transcripts.repositories.persistence import upsert_channel, upsert_transcript, upsert_video
from yt_transcripts.services.pipeline import TranscriptPipeline


class BatchProcessor:
    def __init__(
        self,
        youtube_client: Optional[YouTubeDataClient] = None,
        pipeline: Optional[TranscriptPipeline] = None,
        min_video_seconds: Optional[int] = None,
        max_video_seconds: Optional[int] = None,
    ) -> None:
        self.youtube_client = youtube_client or YouTubeDataClient()
        self.pipeline = pipeline or TranscriptPipeline()
        env_min_video_seconds, env_max_video_seconds = get_transcript_duration_bounds()
        self.min_video_seconds = min_video_seconds if min_video_seconds is not None else env_min_video_seconds
        self.max_video_seconds = max_video_seconds if max_video_seconds is not None else env_max_video_seconds

    def process_latest_videos(
        self,
        channel_ids: list[str],
        max_videos_per_channel: int = 5,
        languages: Optional[list[str]] = None,
        enable_ytdlp_fallback: bool = True,
        enable_whisper_fallback: bool = False,
        whisper_model: str = "base",
        whisper_language: Optional[str] = None,
        output_dir: str = "outputs",
    ) -> list[dict]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        batch_results: list[dict] = []

        with SessionLocal() as session:
            for channel_id in channel_ids:
                videos = self.youtube_client.get_latest_videos(
                    channel_id=channel_id,
                    max_results=max_videos_per_channel,
                )

                for video in videos:
                    if self._should_skip_video(video):
                        transcript = self._build_skipped_transcript_result(video)
                    else:
                        transcript = self.pipeline.get_transcript(
                            video=video.url,
                            languages=languages or ["en"],
                            enable_ytdlp_fallback=enable_ytdlp_fallback,
                            enable_whisper_fallback=enable_whisper_fallback,
                            whisper_model=whisper_model,
                            whisper_language=whisper_language,
                        )
                    self._persist_video_and_transcript(session=session, video=video, transcript=transcript)
                    record = self._build_record(video, transcript.to_dict())
                    batch_results.append(record)
                    self._write_record(output_path=output_path, video=video, record=record)
            session.commit()

        summary_path = output_path / "batch_summary.json"
        summary_path.write_text(json.dumps(batch_results, indent=2), encoding="utf-8")
        return batch_results

    @staticmethod
    def _parse_published_at(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _persist_video_and_transcript(self, *, session, video: VideoItem, transcript: TranscriptResult) -> None:
        channel = upsert_channel(
            session,
            youtube_channel_id=video.channel_id or "unknown",
            title=video.channel_title or "Unknown",
            url=f"https://www.youtube.com/channel/{video.channel_id}" if video.channel_id else "",
        )
        db_video = upsert_video(
            session,
            channel_id=channel.id,
            youtube_video_id=video.video_id,
            title=video.title,
            url=video.url,
            published_at=self._parse_published_at(video.published_at),
            duration_seconds=video.duration_seconds,
            is_short=bool(video.duration_seconds and video.duration_seconds <= 60),
        )
        upsert_transcript(
            session,
            video_id=db_video.id,
            source=transcript.source,
            language=transcript.language_code,
            raw_transcript_json=transcript.to_dict(),
            normalized_text=transcript.transcript_text,
            segment_count=len(transcript.segments),
        )

    @staticmethod
    def _build_record(video: VideoItem, transcript: dict) -> dict:
        return {
            "video": asdict(video),
            "transcript": transcript,
        }

    @staticmethod
    def _write_record(output_path: Path, video: VideoItem, record: dict) -> None:
        file_path = output_path / f"{video.video_id}.json"
        file_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    def _should_skip_video(self, video: VideoItem) -> bool:
        if video.duration_seconds is None:
            return False
        return not (self.min_video_seconds <= video.duration_seconds <= self.max_video_seconds)

    def _build_skipped_transcript_result(self, video: VideoItem) -> TranscriptResult:
        return TranscriptResult(
            video_id=video.video_id,
            source="none",
            no_transcript=True,
            error=(
                f"Video duration {video.duration_seconds}s outside allowed range "
                f"[{self.min_video_seconds}, {self.max_video_seconds}] seconds."
            ),
            metadata={
                "skip_reason": "video_duration_out_of_range",
                "duration_seconds": video.duration_seconds,
                "min_video_seconds": self.min_video_seconds,
                "max_video_seconds": self.max_video_seconds,
            },
        )
