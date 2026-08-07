from __future__ import annotations

import json

from sqlalchemy import inspect, text

from yt_transcripts.db.models import VideoAnalysisTopic
from yt_transcripts.db.session import _normalized_database_url, get_engine

VIDEO_ANALYSIS_TABLE = VideoAnalysisTopic.__table__


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def _ensure_video_analysis_table(connection) -> None:
    VIDEO_ANALYSIS_TABLE.create(bind=connection, checkfirst=True)
    for index in VIDEO_ANALYSIS_TABLE.indexes:
        index.create(bind=connection, checkfirst=True)


def main() -> None:
    db_url = _normalized_database_url()
    engine = get_engine(database_url=db_url)

    with engine.begin() as connection:
        inspector = inspect(connection)
        _ensure_video_analysis_table(connection)

        inspector = inspect(connection)
        if _table_exists(inspector, "video_analyses"):
            legacy_rows = connection.execute(
                text("SELECT analysis_run_id, video_id, main_topics_json FROM video_analyses WHERE main_topics_json IS NOT NULL")
            ).mappings()
            for row in legacy_rows:
                connection.execute(
                    VIDEO_ANALYSIS_TABLE.delete().where(
                        VIDEO_ANALYSIS_TABLE.c.analysis_run_id == row["analysis_run_id"],
                        VIDEO_ANALYSIS_TABLE.c.video_id == row["video_id"],
                    )
                )
                topics = row["main_topics_json"]
                if isinstance(topics, str):
                    try:
                        topics = json.loads(topics)
                    except json.JSONDecodeError:
                        topics = []
                if not isinstance(topics, list):
                    continue

                for topic_payload in topics:
                    if not isinstance(topic_payload, dict):
                        continue
                    analysis = topic_payload.get("analysis") if isinstance(topic_payload.get("analysis"), dict) else {}
                    connection.execute(
                        VIDEO_ANALYSIS_TABLE.insert().values(
                            analysis_run_id=row["analysis_run_id"],
                            video_id=row["video_id"],
                            topic=topic_payload.get("topic"),
                            event_title=topic_payload.get("event_title"),
                            summary=topic_payload.get("summary"),
                            entities_json=topic_payload.get("entities"),
                            time_context=topic_payload.get("time_context"),
                            perspective=topic_payload.get("perspective"),
                            framing=analysis.get("framing"),
                            narrative=analysis.get("narrative"),
                            rhetoric_json=analysis.get("rhetoric"),
                            influence=analysis.get("influence"),
                        )
                    )

    print("Migration complete: video_analysis table and indexes are ready; backfill attempted from video_analyses.")


if __name__ == "__main__":
    main()
