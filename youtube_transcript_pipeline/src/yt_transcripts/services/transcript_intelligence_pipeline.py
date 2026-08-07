from __future__ import annotations

import json
import logging
import re
from errno import EACCES, EROFS
from pathlib import Path

from yt_transcripts.db.session import SessionLocal
from sqlalchemy import select

from yt_transcripts.db.models import Transcript
from yt_transcripts.repositories.persistence import (
    complete_analysis_run,
    create_analysis_run,
    get_existing_analysis_run,
    get_video_by_youtube_id,
    save_video_analysis_topics,
    save_video_analysis,
)
from yt_transcripts.services.prompt_service import PromptService
from yt_transcripts.services.topic_aggregation_service import TopicAggregationService
from yt_transcripts.services.topic_perspective_analysis_service import TopicPerspectiveAnalysisService


class TranscriptIntelligencePipeline:
    def __init__(self, prompt_service: PromptService | None = None, analysis_service: TopicPerspectiveAnalysisService | None = None, aggregation_service: TopicAggregationService | None = None) -> None:
        self.prompt_service = prompt_service or PromptService()
        self.analysis_service = analysis_service or TopicPerspectiveAnalysisService()
        self.aggregation_service = aggregation_service or TopicAggregationService()

    def run(self, *, input_dir: str, model: str, prompt_file: str, output_file: str | None = None, prompt_version: str = "v1", force: bool = False) -> dict:
        logger = logging.getLogger(__name__)
        prompt_text = self.prompt_service.load_prompt(prompt_file)
        transcript_records = self._load_transcript_records(input_dir)

        analysis_rows: list[dict] = []
        with SessionLocal() as session:
            for record in transcript_records:
                transcript_text = record.get("transcript_text", "")
                if not transcript_text:
                    continue
                db_video = get_video_by_youtube_id(session, youtube_video_id=record.get("video_id", ""))
                if not db_video:
                    continue
                existing = get_existing_analysis_run(session, video_id=db_video.id, analysis_type="topic_perspective", model_name=model, prompt_version=prompt_version)
                if existing and existing.status == "completed" and not force:
                    continue
                transcript_row = session.scalar(select(Transcript).where(Transcript.video_id == db_video.id))
                if not transcript_row:
                    continue
                run = existing or create_analysis_run(session, video_id=db_video.id, transcript_id=transcript_row.id, analysis_type="topic_perspective", model_name=model, prompt_version=prompt_version, prompt_text=prompt_text)

                analysis_payload = self.analysis_service.analyze(model=model, prompt_text=prompt_text, transcript_text=transcript_text, video_id=record.get("video_id", ""), channel_id=record.get("channel_id"), channel_title=record.get("channel_title"))
                normalized_payload = self._normalize_analysis_payload(analysis_payload)
                mapped_analysis = self._map_analysis_fields(normalized_payload)
                raw_response = json.dumps(analysis_payload)
                complete_analysis_run(session, analysis_run=run, raw_response=raw_response, parsed_response_json=normalized_payload)
                parsed_values_to_save = {
                    "analysis_run_id": run.id,
                    "video_id": db_video.id,
                    "summary": mapped_analysis.get("summary"),
                    "main_topics_json": mapped_analysis.get("main_topics"),
                    "claims_json": mapped_analysis.get("claims"),
                    "perspective_json": mapped_analysis.get("perspective"),
                    "sentiment_json": mapped_analysis.get("sentiment"),
                    "bias_signals_json": mapped_analysis.get("bias_signals"),
                    "rhetoric_signals_json": mapped_analysis.get("rhetoric_signals"),
                    "influence_signals_json": mapped_analysis.get("influence_signals"),
                    "confidence_score": mapped_analysis.get("confidence_score"),
                }
                print(json.dumps({"saved_parsed_values": parsed_values_to_save}, ensure_ascii=False, default=str))
                topic_rows_inserted = save_video_analysis_topics(
                    session,
                    analysis_run_id=parsed_values_to_save["analysis_run_id"],
                    video_id=parsed_values_to_save["video_id"],
                    main_topics_json=parsed_values_to_save["main_topics_json"],
                )
                save_video_analysis(
                    session,
                    analysis_run_id=parsed_values_to_save["analysis_run_id"],
                    video_id=parsed_values_to_save["video_id"],
                    summary=parsed_values_to_save["summary"],
                    main_topics_json=None,
                    claims_json=parsed_values_to_save["claims_json"],
                    perspective_json=parsed_values_to_save["perspective_json"],
                    sentiment_json=parsed_values_to_save["sentiment_json"],
                    bias_signals_json=parsed_values_to_save["bias_signals_json"],
                    rhetoric_signals_json=parsed_values_to_save["rhetoric_signals_json"],
                    influence_signals_json=parsed_values_to_save["influence_signals_json"],
                    confidence_score=parsed_values_to_save["confidence_score"],
                )
                logger.info(
                    "Persisted topic rows",
                    extra={
                        "analysis_run_id": parsed_values_to_save["analysis_run_id"],
                        "video_id": parsed_values_to_save["video_id"],
                        "topic_rows_inserted": topic_rows_inserted,
                    },
                )
                session.commit()
                analysis_rows.append({"video_id": record.get("video_id"), "channel_id": record.get("channel_id"), "channel_title": record.get("channel_title"), "analysis": analysis_payload})

        aggregated_collections = self.aggregation_service.aggregate(analysis_rows)
        result = {"model": model, "input_dir": str(Path(input_dir).resolve()), "analyzed_videos": len(analysis_rows), "aggregations": aggregated_collections}

        if output_file:
            output_path = Path(output_file)
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            except OSError as exc:
                if exc.errno in {EACCES, EROFS}:
                    raise RuntimeError("Output path is not writable. " f"Received --output-file '{output_file}'. " "Use a writable project path such as " "'outputs/topic_perspectives_aggregate.json'.") from exc
                raise

        return result

    @staticmethod
    def _load_transcript_records(input_dir: str) -> list[dict]:
        records: list[dict] = []
        for file_path in sorted(Path(input_dir).glob("*.json")):
            if file_path.name in {"batch_summary.json", "topic_perspectives_aggregate.json"}:
                continue
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            transcript = payload.get("transcript", {})
            video = payload.get("video", {})
            if transcript.get("no_transcript"):
                continue
            records.append({"video_id": video.get("video_id"), "channel_id": video.get("channel_id"), "channel_title": video.get("channel_title"), "transcript_text": transcript.get("transcript_text", "")})
        return records

    @staticmethod
    def _normalize_analysis_payload(analysis_payload: dict | str | None) -> dict:
        if analysis_payload is None:
            return {}

        payload: dict | str = analysis_payload
        if isinstance(payload, str):
            text = payload.strip()
            if text.startswith("```"):
                fence_match = re.match(r"^```[a-zA-Z0-9_-]*\s*(.*?)\s*```$", text, re.DOTALL)
                if fence_match:
                    text = fence_match.group(1).strip()
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return {}
            if not isinstance(parsed, dict):
                return {}
            payload = parsed

        if not isinstance(payload, dict):
            return {}

        root = payload
        while isinstance(root, dict):
            for wrapper_key in ("analysis", "result", "data", "response", "output"):
                candidate = root.get(wrapper_key)
                if isinstance(candidate, dict):
                    root = candidate
                    break
            else:
                break

        main_topics_candidate = root.get("main_topics")
        if (
            isinstance(main_topics_candidate, dict)
            and root.get("summary") is None
            and any(key in main_topics_candidate for key in ("summary", "topics", "claims", "perspectives", "sentiment_analysis", "bias", "rhetorical_signals", "influence", "confidence"))
        ):
            return main_topics_candidate

        return root

    @staticmethod
    def _map_analysis_fields(analysis_payload: dict) -> dict:
        if not isinstance(analysis_payload, dict):
            return {}
        if not analysis_payload:
            return {}

        def pick(*keys: str):
            for key in keys:
                if key in root and root.get(key) is not None:
                    return root.get(key)
            return None

        root = analysis_payload
        topics_value = pick("main_topics", "topics")
        if isinstance(topics_value, dict) and any(
            key in topics_value
            for key in ("summary", "claims", "key_claims", "perspective", "perspectives", "sentiment", "sentiment_analysis", "bias", "rhetorical_signals", "influence")
        ):
            topics_value = topics_value.get("topics")

        return {
            "summary": pick("summary", "overall_summary"),
            "main_topics": topics_value,
            "claims": pick("claims", "key_claims"),
            "perspective": pick("perspective", "perspectives"),
            "sentiment": pick("sentiment", "sentiment_analysis"),
            "bias_signals": pick("bias_signals", "bias"),
            "rhetoric_signals": pick("rhetoric_signals", "rhetorical_signals"),
            "influence_signals": pick("influence_signals", "influence"),
            "confidence_score": pick("confidence_score", "confidence"),
        }
