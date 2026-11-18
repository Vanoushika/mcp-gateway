"""Storage — SQLAlchemy over SQLite by default, PostgreSQL-ready.

Call records are stored as JSON payloads in one small table, so the
same code works against SQLite locally and PostgreSQL in production
via the ``DATABASE_URL`` environment variable.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Float, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .models import CallRecord

Base = declarative_base()


class CallRow(Base):
    __tablename__ = "calls"
    id = Column(String, primary_key=True)
    tool_name = Column(String, nullable=False)
    server = Column(String, nullable=False)
    arguments = Column(JSON, nullable=False)
    result = Column(JSON, nullable=False)
    is_error = Column(String, nullable=False)
    duration_ms = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False)


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///./gateway.db")


def make_session_factory(database_url: str | None = None):
    url = database_url or _database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Store:
    """Thin persistence layer for gateway call records."""

    def __init__(self, database_url: str | None = None) -> None:
        self._sessions = make_session_factory(database_url)

    def record_call(
        self,
        tool_name: str,
        server: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        is_error: bool,
        duration_ms: float,
    ) -> CallRecord:
        record = CallRecord(
            id=str(uuid.uuid4()),
            tool_name=tool_name,
            server=server,
            arguments=arguments,
            result=result,
            is_error=is_error,
            duration_ms=duration_ms,
            created_at=datetime.now(timezone.utc),
        )
        session = self._sessions()
        try:
            session.add(
                CallRow(
                    id=record.id,
                    tool_name=record.tool_name,
                    server=record.server,
                    arguments=json.loads(json.dumps(record.arguments)),
                    result=json.loads(json.dumps(record.result)),
                    is_error="true" if record.is_error else "false",
                    duration_ms=record.duration_ms,
                    created_at=record.created_at,
                )
            )
            session.commit()
        finally:
            session.close()
        return record

    def list_calls(self, limit: int = 50) -> list[CallRecord]:
        session = self._sessions()
        try:
            rows = (
                session.query(CallRow)
                .order_by(CallRow.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                CallRecord(
                    id=row.id,
                    tool_name=row.tool_name,
                    server=row.server,
                    arguments=row.arguments,
                    result=row.result,
                    is_error=row.is_error == "true",
                    duration_ms=row.duration_ms,
                    created_at=row.created_at,
                )
                for row in rows
            ]
        finally:
            session.close()

    def get_call(self, call_id: str) -> CallRecord | None:
        session = self._sessions()
        try:
            row = session.query(CallRow).filter(CallRow.id == call_id).first()
            if row is None:
                return None
            return CallRecord(
                id=row.id,
                tool_name=row.tool_name,
                server=row.server,
                arguments=row.arguments,
                result=row.result,
                is_error=row.is_error == "true",
                duration_ms=row.duration_ms,
                created_at=row.created_at,
            )
        finally:
            session.close()
