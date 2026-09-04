"""Portable column types.

GUID stores as native UUID on Postgres and as a CHAR(36) on any other
dialect (SQLite, used by the unit test suite in tests/conftest.py).
Without this, models using `postgresql.UUID` directly fail to create
tables under SQLite, which would silently block fast, DB-less unit
tests and push everything into slow integration tests.

Embedding is the same idea for vector columns: pgvector's `Vector` type
on Postgres, plain JSON-encoded text on any other dialect. Similarity
search (app/core/vector_math.py) ranks in Python rather than relying on
pgvector's `<->` operator, specifically so it works identically — and
is testable — on both backends. Swapping to a native `ORDER BY
embedding <-> :query` query is a valid future optimization once this
runs at a scale where in-Python ranking of candidate rows is too slow;
noted rather than done here since it can't be verified against a real
Postgres+pgvector instance in this sandbox.
"""
import json
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import CHAR, Text, TypeDecorator


class GUID(TypeDecorator):
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return str(value)
        if not isinstance(value, uuid.UUID):
            return str(uuid.UUID(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)


class Embedding(TypeDecorator):
    """Stores an embedding vector. `dim` must match the configured AI
    provider's embedding dimensionality (see settings.EMBEDDING_DIMENSIONS)."""

    impl = Text
    cache_ok = True

    def __init__(self, dim: int, *args, **kwargs):
        self.dim = dim
        super().__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        return json.dumps(list(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return list(value)
        return json.loads(value)
