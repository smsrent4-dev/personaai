"""Knowledge base models.

A KnowledgeDocument is the uploaded/pasted/fetched source (a PDF, a
pasted FAQ, a scraped URL). It gets split into KnowledgeChunks, each
independently embedded, which is what RAG retrieval actually searches
over — chunks, not whole documents, since a whole document is usually
too large (and too unfocused) to embed as one vector meaningfully.

`agent_id` nullable on the document means "shared knowledge available
to every agent this user owns" (e.g. a company policy doc). A non-null
`agent_id` scopes it to one agent (e.g. a product sheet only the Sales
Agent needs).
"""
import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.core.types import GUID, Embedding
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class KnowledgeSourceType(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"
    TEXT = "text"
    MARKDOWN = "markdown"
    URL = "url"
    FAQ = "faq"


class KnowledgeStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class KnowledgeDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "knowledge_documents"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[KnowledgeSourceType] = mapped_column(
        Enum(KnowledgeSourceType, name="knowledge_source_type", values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    status: Mapped[KnowledgeStatus] = mapped_column(
        Enum(KnowledgeStatus, name="knowledge_status", values_callable=lambda x: [e.value for e in x]), default=KnowledgeStatus.PENDING, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        "KnowledgeChunk", back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<KnowledgeDocument {self.title!r} ({self.status.value})>"


class KnowledgeChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "knowledge_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalized so chunk queries can filter by owner without a join.
    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Embedding(settings.EMBEDDING_DIMENSIONS), nullable=False)

    document: Mapped["KnowledgeDocument"] = relationship("KnowledgeDocument", back_populates="chunks")
