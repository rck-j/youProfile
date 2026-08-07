from __future__ import annotations

from typing import Any

from yt_transcripts.clients.openai_analysis_client import OpenAIAnalysisClient


class TopicPerspectiveAnalysisService:
    """Runs topic/perspective extraction for a single transcript."""

    def __init__(self, openai_client: OpenAIAnalysisClient | None = None) -> None:
        self.openai_client = openai_client or OpenAIAnalysisClient()

    def analyze(
        self,
        *,
        model: str,
        prompt_text: str,
        transcript_text: str,
        video_id: str,
        channel_id: str | None,
        channel_title: str | None,
    ) -> dict[str, Any]:
        payload = self.openai_client.analyze_topics_and_perspectives(
            model=model,
            system_prompt=prompt_text,
            transcript_text=transcript_text,
            video_id=video_id,
            channel_id=channel_id,
            channel_title=channel_title,
        )
        if not isinstance(payload, dict):
            return {}

        cleaned_payload: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, list):
                cleaned_entries: list[dict[str, str]] = []
                for entry in value:
                    if not isinstance(entry, dict):
                        continue
                    normalized_entry: dict[str, str] = {}
                    for item_key, item_value in entry.items():
                        item_text = str(item_value).strip()
                        if item_text:
                            normalized_entry[str(item_key)] = item_text
                    if normalized_entry:
                        cleaned_entries.append(normalized_entry)
                cleaned_payload[str(key)] = cleaned_entries
            elif isinstance(value, (str, int, float, bool)):
                cleaned_payload[str(key)] = value
        return cleaned_payload
