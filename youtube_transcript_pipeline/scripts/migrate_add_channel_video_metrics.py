from __future__ import annotations

from sqlalchemy import inspect, text

from yt_transcripts.db.session import _normalized_database_url, get_engine


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    columns = inspector.get_columns(table_name)
    return any(column.get("name") == column_name for column in columns)


def _add_column_if_missing(connection, inspector, table_name: str, column_name: str, sql_type: str) -> bool:
    if _column_exists(inspector, table_name, column_name):
        return False
    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}"))
    return True


def main() -> None:
    db_url = _normalized_database_url()
    engine = get_engine(database_url=db_url)

    applied: list[str] = []
    with engine.begin() as connection:
        inspector = inspect(connection)

        table_names = set(inspector.get_table_names())
        if "channels" not in table_names or "videos" not in table_names:
            raise RuntimeError(
                "Expected tables 'channels' and 'videos' to exist. "
                f"DATABASE_URL={db_url} has tables={sorted(table_names)}. "
                "Run init-db before this migration."
            )

        if _add_column_if_missing(connection, inspector, "channels", "subscriber_count", "INTEGER"):
            applied.append("channels.subscriber_count")

        inspector = inspect(connection)
        if _add_column_if_missing(connection, inspector, "videos", "view_count", "INTEGER"):
            applied.append("videos.view_count")

        inspector = inspect(connection)
        if _add_column_if_missing(connection, inspector, "videos", "like_count", "INTEGER"):
            applied.append("videos.like_count")

    if applied:
        print("Migration complete. Added columns:")
        for item in applied:
            print(f"- {item}")
    else:
        print("Migration complete. No changes were required.")


if __name__ == "__main__":
    main()
