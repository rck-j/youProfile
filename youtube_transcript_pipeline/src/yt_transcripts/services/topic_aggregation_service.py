from __future__ import annotations

import json
from collections import defaultdict


class TopicAggregationService:
    """Aggregates prompt-defined collections across channels."""

    def aggregate(self, analysis_rows: list[dict]) -> dict[str, list[dict]]:
        collection_buckets: dict[str, dict[str, dict]] = defaultdict(dict)

        for row in analysis_rows:
            for collection_name, items in row.get("analysis", {}).items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict) or not item:
                        continue
                    item_key = json.dumps(item, sort_keys=True)
                    bucket = collection_buckets[collection_name].setdefault(
                        item_key,
                        {
                            "item": item,
                            "channels": defaultdict(
                                lambda: {
                                    "channel_id": None,
                                    "channel_title": None,
                                    "video_ids": set(),
                                }
                            ),
                        },
                    )

                    channel_key = row.get("channel_id") or row.get("channel_title") or "unknown_channel"
                    channel_entry = bucket["channels"][channel_key]
                    channel_entry["channel_id"] = row.get("channel_id")
                    channel_entry["channel_title"] = row.get("channel_title")
                    if row.get("video_id"):
                        channel_entry["video_ids"].add(row.get("video_id"))

        aggregated_collections: dict[str, list[dict]] = {}
        for collection_name, buckets in collection_buckets.items():
            collection_items: list[dict] = []
            for bucket in buckets.values():
                channels = []
                for channel_data in bucket["channels"].values():
                    channels.append(
                        {
                            "channel_id": channel_data["channel_id"],
                            "channel_title": channel_data["channel_title"],
                            "video_ids": sorted(channel_data["video_ids"]),
                        }
                    )

                collection_items.append(
                    {
                        "item": bucket["item"],
                        "channels": sorted(
                            channels,
                            key=lambda item: (
                                item["channel_title"] or "",
                                item["channel_id"] or "",
                            ),
                        ),
                    }
                )

            aggregated_collections[collection_name] = sorted(
                collection_items,
                key=lambda entry: json.dumps(entry["item"], sort_keys=True).casefold(),
            )

        return dict(sorted(aggregated_collections.items(), key=lambda entry: entry[0].casefold()))
