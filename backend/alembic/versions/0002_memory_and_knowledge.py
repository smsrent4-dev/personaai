"""memory + knowledge base: pgvector extension, memory_entries, knowledge_documents, knowledge_chunks

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 768  # must match settings.EMBEDDING_DIMENSIONS


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    memory_type = postgresql.ENUM("fact", "preference", "event", "conversation_summary", name="memory_type", create_type=False)
    memory_source = postgresql.ENUM("teach", "conversation", "manual", name="memory_source", create_type=False)
    knowledge_source_type = postgresql.ENUM("pdf", "docx", "text", "markdown", "url", "faq", name="knowledge_source_type", create_type=False)
    knowledge_status = postgresql.ENUM("pending", "processing", "ready", "failed", name="knowledge_status", create_type=False)

    bind = op.get_bind()
    memory_type.create(bind, checkfirst=True)
    memory_source.create(bind, checkfirst=True)
    knowledge_source_type.create(bind, checkfirst=True)
    knowledge_status.create(bind, checkfirst=True)

    op.create_table(
        "memory_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("memory_type", memory_type, nullable=False),
        sa.Column("source", memory_source, nullable=False, server_default="manual"),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
    )
    op.create_index("ix_memory_entries_owner_id", "memory_entries", ["owner_id"])
    op.create_index("ix_memory_entries_agent_id", "memory_entries", ["agent_id"])

    op.create_table(
        "knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("source_type", knowledge_source_type, nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=True),
        sa.Column("file_path", sa.String(1024), nullable=True),
        sa.Column("status", knowledge_status, nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.create_index("ix_knowledge_documents_owner_id", "knowledge_documents", ["owner_id"])
    op.create_index("ix_knowledge_documents_agent_id", "knowledge_documents", ["agent_id"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.create_index("ix_knowledge_chunks_owner_id", "knowledge_chunks", ["owner_id"])


def downgrade() -> None:
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.drop_table("memory_entries")

    bind = op.get_bind()
    postgresql.ENUM(name="knowledge_status", create_type=False).drop(bind, checkfirst=True)
    postgresql.ENUM(name="knowledge_source_type", create_type=False).drop(bind, checkfirst=True)
    postgresql.ENUM(name="memory_source", create_type=False).drop(bind, checkfirst=True)
    postgresql.ENUM(name="memory_type", create_type=False).drop(bind, checkfirst=True)
