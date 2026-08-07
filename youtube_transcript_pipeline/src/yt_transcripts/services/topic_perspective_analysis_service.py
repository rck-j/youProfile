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
            normalized_value = self._normalize_value(value)
            if normalized_value is not None:
                cleaned_payload[str(key)] = normalized_value
        return cleaned_payload

    @classmethod
    def _normalize_value(cls, value: Any) -> Any:
        if value is None:
            return None

        if isinstance(value, dict):
            normalized: dict[str, Any] = {}
            for item_key, item_value in value.items():
                normalized_item = cls._normalize_value(item_value)
                if normalized_item is not None:
                    normalized[str(item_key)] = normalized_item
            return normalized if normalized else None

        if isinstance(value, list):
            normalized_list: list[Any] = []
            for item in value:
                normalized_item = cls._normalize_value(item)
                if normalized_item is not None:
                    normalized_list.append(normalized_item)
            return normalized_list if normalized_list else None

        if isinstance(value, str):
            text = value.strip()
            return text or None

        if isinstance(value, (int, float, bool)):
            return value

        return str(value).strip() or None
