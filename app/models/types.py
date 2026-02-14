"""Dialect-agnostic types for SQLite (tests) and PostgreSQL (production).

PostgreSQL-specific ARRAY and JSONB are not supported by SQLite. These types
use ARRAY/JSONB on PostgreSQL and JSON on SQLite for cross-database compatibility.
"""

from __future__ import annotations

import uuid
from typing import Any, List, Optional

from sqlalchemy import JSON, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.types import TypeDecorator


class StringArray(TypeDecorator):
    """List of strings: ARRAY on PostgreSQL, JSON on SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(Text))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Optional[List[str]], dialect) -> Optional[Any]:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return value

    def process_result_value(self, value: Optional[Any], dialect) -> Optional[List[str]]:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value) if value else []
        return value if isinstance(value, list) else []


class UUIDArray(TypeDecorator):
    """List of UUIDs: ARRAY(UUID) on PostgreSQL, JSON on SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(UUID(as_uuid=True)))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Optional[List[uuid.UUID]], dialect) -> Optional[Any]:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return [str(v) for v in value]

    def process_result_value(self, value: Optional[Any], dialect) -> Optional[List[uuid.UUID]]:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value) if value else []
        if not value:
            return []
        return [uuid.UUID(s) if isinstance(s, str) else s for s in value]


class JSONBCompat(TypeDecorator):
    """Dict/list: JSONB on PostgreSQL, JSON on SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())
