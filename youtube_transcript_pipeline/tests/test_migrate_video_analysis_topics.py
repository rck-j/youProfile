from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from yt_transcripts.db.models import Base

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "migrate_video_analysis_topics.py"
SPEC = importlib.util.spec_from_file_location("migrate_video_analysis_topics", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def test_video_analysis_table_compiles_to_postgres_ddl() -> None:
    dialect = postgresql.dialect()

    table_sql = str(CreateTable(migration.VIDEO_ANALYSIS_TABLE).compile(dialect=dialect))
    index_sql = [
        str(CreateIndex(index).compile(dialect=dialect))
        for index in sorted(migration.VIDEO_ANALYSIS_TABLE.indexes, key=lambda item: item.name or "")
    ]

    assert "DATETIME" not in table_sql
    assert "TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in table_sql
    assert "entities_json JSON" in table_sql
    assert "rhetoric_json JSON" in table_sql
    assert "FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs" in table_sql
    assert "FOREIGN KEY(video_id) REFERENCES videos" in table_sql
    assert "CREATE INDEX ix_video_analysis_analysis_run_id ON video_analysis (analysis_run_id)" in index_sql
    assert "CREATE INDEX ix_video_analysis_video_id ON video_analysis (video_id)" in index_sql
    assert "CREATE INDEX ix_video_analysis_topic ON video_analysis (topic)" in index_sql


def test_video_analysis_insert_compiles_json_bind_for_postgres() -> None:
    dialect = postgresql.dialect()

    statement = migration.VIDEO_ANALYSIS_TABLE.insert().values(
        analysis_run_id=1,
        video_id=2,
        topic="energy",
        event_title="Energy Transition",
        entities_json=["DOE"],
        time_context="2026",
        rhetoric_json={"appeal": "authority"},
    )
    insert_sql = str(statement.compile(dialect=dialect))

    assert "entities_json" in insert_sql
    assert "rhetoric_json" in insert_sql
    assert "::JSON" in insert_sql


def test_migration_backfills_legacy_topics_from_sqlite_database(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(bind=engine)

    topics = [
        {
            "topic": "energy",
            "event_title": "Energy Transition",
            "summary": "Topic summary",
            "entities": ["DOE", "EPA"],
            "time_context": "2026 policy cycle",
            "perspective": "Supportive",
            "analysis": {
                "framing": "economic",
                "narrative": "growth",
                "rhetoric": {"appeal": "jobs"},
                "influence": "high",
            },
        }
    ]
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO channels (id, youtube_channel_id, title, url)
                VALUES (1, 'channel-1', 'Channel 1', 'https://youtube.com/channel-1')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO videos (id, channel_id, youtube_video_id, title, url, is_short)
                VALUES (2, 1, 'video-1', 'Video 1', 'https://youtube.com/watch?v=video-1', 0)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO transcripts (id, video_id, source, raw_transcript_json, normalized_text, segment_count)
                VALUES (3, 2, 'api', '{}', 'transcript text', 1)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO analysis_runs (
                    id, video_id, transcript_id, analysis_type, model_name,
                    prompt_version, prompt_text, status
                ) VALUES (4, 2, 3, 'topic_perspective', 'gpt', 'v1', 'prompt', 'completed')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO video_analyses (analysis_run_id, video_id, main_topics_json)
                VALUES (4, 2, :topics)
                """
            ),
            {"topics": json.dumps(topics)},
        )

    monkeypatch.setenv("DATABASE_URL", database_url)
    migration.main()

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert "video_analysis" in inspector.get_table_names()
        assert {index["name"] for index in inspector.get_indexes("video_analysis")} >= {
            "ix_video_analysis_analysis_run_id",
            "ix_video_analysis_video_id",
            "ix_video_analysis_topic",
        }
        row = connection.execute(
            text(
                """
                SELECT topic, event_title, summary, entities_json, time_context, perspective, framing, narrative, rhetoric_json, influence
                FROM video_analysis
                WHERE analysis_run_id = 4 AND video_id = 2
                """
            )
        ).mappings().one()

    assert row["topic"] == "energy"
    assert row["event_title"] == "Energy Transition"
    assert row["summary"] == "Topic summary"
    assert json.loads(row["entities_json"]) == ["DOE", "EPA"]
    assert row["time_context"] == "2026 policy cycle"
    assert row["perspective"] == "Supportive"
    assert row["framing"] == "economic"
    assert row["narrative"] == "growth"
    assert json.loads(row["rhetoric_json"]) == {"appeal": "jobs"}
    assert row["influence"] == "high"
