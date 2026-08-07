from __future__ import annotations

from sqlalchemy import inspect, text

from yt_transcripts.db.session import _normalized_database_url, get_engine


def _add_column_if_missing(connection, inspector, *, table_name: str, column_name: str, ddl_type: str) -> None:
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in columns:
        return
    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl_type}"))


def main() -> None:
    db_url = _normalized_database_url()
    engine = get_engine(database_url=db_url)

    with engine.begin() as connection:
        inspector = inspect(connection)
        table_name = "video_analysis"
        if table_name not in set(inspector.get_table_names()):
            raise RuntimeError("video_analysis table does not exist. Run migrate_video_analysis_topics.py first.")

        _add_column_if_missing(connection, inspector, table_name=table_name, column_name="event_title", ddl_type="VARCHAR(512)")
        inspector = inspect(connection)
        _add_column_if_missing(connection, inspector, table_name=table_name, column_name="entities_json", ddl_type="JSON")
        inspector = inspect(connection)
        _add_column_if_missing(connection, inspector, table_name=table_name, column_name="time_context", ddl_type="VARCHAR(256)")

    print("Migration complete: added event_title, entities_json, and time_context columns to video_analysis.")


if __name__ == "__main__":
    main()
