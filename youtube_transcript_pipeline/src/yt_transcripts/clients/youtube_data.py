from __future__ import annotations

import os
import re
from typing import Optional

from googleapiclient.discovery import build

from yt_transcripts.models.video import VideoItem


_ISO8601_DURATION_PATTERN = re.compile(
    r"^P(?:\d+Y)?(?:\d+M)?(?:\d+D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def parse_iso8601_duration_to_seconds(duration: str) -> Optional[int]:
    match = _ISO8601_DURATION_PATTERN.match(duration)
    if not match:
        return None
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return (hours * 3600) + (minutes * 60) + seconds


class YouTubeDataClient:
    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        if not self.api_key:
            raise ValueError("YOUTUBE_API_KEY is required.")
        self._service = build("youtube", "v3", developerKey=self.api_key)

    def get_uploads_playlist_id(self, channel_id: str) -> str:
        response = (
            self._service.channels()
            .list(part="contentDetails,snippet,statistics", id=channel_id)
            .execute()
        )
        items = response.get("items", [])
        if not items:
            raise ValueError(f"Channel not found: {channel_id}")
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    def get_latest_videos(self, channel_id: str, max_results: int = 5) -> list[VideoItem]:
        uploads_playlist_id = self.get_uploads_playlist_id(channel_id)
        response = (
            self._service.playlistItems()
            .list(
                part="snippet,contentDetails",
                playlistId=uploads_playlist_id,
                maxResults=max_results,
            )
            .execute()
        )

        items = response.get("items", [])
        video_ids = [
            item.get("snippet", {}).get("resourceId", {}).get("videoId")
            for item in items
            if item.get("snippet", {}).get("resourceId", {}).get("videoId")
        ]
        video_details_by_id = self._get_video_details_by_video_id(video_ids)

        videos: list[VideoItem] = []
        for item in items:
            snippet = item.get("snippet", {})
            resource_id = snippet.get("resourceId", {})
            video_id = resource_id.get("videoId")
            if not video_id:
                continue
            videos.append(
                VideoItem(
                    video_id=video_id,
                    title=snippet.get("title", ""),
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    duration_seconds=video_details_by_id.get(video_id, {}).get("duration_seconds"),
                    view_count=video_details_by_id.get(video_id, {}).get("view_count"),
                    like_count=video_details_by_id.get(video_id, {}).get("like_count"),
                    comment_count=video_details_by_id.get(video_id, {}).get("comment_count"),
                    published_at=snippet.get("publishedAt"),
                    channel_id=snippet.get("channelId"),
                    channel_title=snippet.get("channelTitle"),
                    description=snippet.get("description"),
                )
            )
        return videos

    def _get_video_details_by_video_id(self, video_ids: list[str]) -> dict[str, dict[str, Optional[int]]]:
        if not video_ids:
            return {}
        response = (
            self._service.videos()
            .list(
                part="contentDetails,statistics",
                id=",".join(video_ids),
            )
            .execute()
        )
        details: dict[str, dict[str, Optional[int]]] = {}
        for item in response.get("items", []):
            video_id = item.get("id")
            if not video_id:
                continue
            duration = item.get("contentDetails", {}).get("duration", "")
            stats = item.get("statistics", {})
            details[video_id] = {
                "duration_seconds": parse_iso8601_duration_to_seconds(duration),
                "view_count": int(stats.get("viewCount")) if stats.get("viewCount") else None,
                "like_count": int(stats.get("likeCount")) if stats.get("likeCount") else None,
                "comment_count": int(stats.get("commentCount")) if stats.get("commentCount") else None,
            }
        return details

    def find_channel_by_name(self, channel_name: str) -> Optional[dict[str, str]]:
        search_response = (
            self._service.search()
            .list(
                part="snippet",
                q=channel_name,
                type="channel",
                maxResults=1,
            )
            .execute()
        )
        items = search_response.get("items", [])
        if not items:
            return None

        snippet = items[0].get("snippet", {})
        id_payload = items[0].get("id", {})
        channel_id = id_payload.get("channelId")
        if not channel_id:
            return None

        return {
            "name": snippet.get("channelTitle") or channel_name,
            "channel_id": channel_id,
        }


    def get_channel_statistics(self, channel_id: str) -> dict[str, Optional[int | str]]:
        response = self._service.channels().list(part="snippet,statistics", id=channel_id).execute()
        items = response.get("items", [])
        if not items:
            return {}
        item = items[0]
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})
        return {
            "title": snippet.get("title"),
            "url": f"https://www.youtube.com/channel/{channel_id}",
            "subscriber_count": int(stats.get("subscriberCount")) if stats.get("subscriberCount") else None,
            "total_view_count": int(stats.get("viewCount")) if stats.get("viewCount") else None,
            "video_count": int(stats.get("videoCount")) if stats.get("videoCount") else None,
        }
