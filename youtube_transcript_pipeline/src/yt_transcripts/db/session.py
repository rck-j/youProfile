from __future__ import annotations

import os
from collections.abc import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from yt_transcripts.db.models import Base

load_dotenv()


def _normalized_database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///yt_transcripts.db")
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def get_engine(database_url: str | None = None) -> Engine:
    url = database_url or _normalized_database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, echo=False, connect_args=connect_args)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, class_=Session, bind=get_engine())


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db(engine: Engine | None = None) -> None:
    db_engine = engine or SessionLocal.kw["bind"]
    Base.metadata.create_all(bind=db_engine)
