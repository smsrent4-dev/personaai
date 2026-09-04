"""KnowledgeService — document lifecycle and RAG search.

Ingestion (`ingest_document`) is deliberately a plain async method, not
tied to being called from an HTTP request or a Celery task — both
call it. See app/worker.py for the Celery wrapper, and
app/api/v1/endpoints/knowledge.py for why upload endpoints currently
call it inline rather than via `.delay()`.
"""
import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.vector_math import top_k_by_similarity
from app.core.plan_limits import enforce_knowledge_document_limit
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeSourceType, KnowledgeStatus
from app.models.notification import NotificationType
from app.models.user import User
from app.services.ai import AIProvider, get_ai_provider
from app.services.knowledge.chunking import chunk_text
from app.services.knowledge.extractors import ExtractionError, extract_text, extract_text_from_html
from app.services.knowledge.storage import StorageBackend, get_storage_backend
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class KnowledgeService:
    def __init__(
        self,
        db: AsyncSession,
        ai_provider: AIProvider | None = None,
        storage: StorageBackend | None = None,
    ):
        self.db = db
        self.ai_provider = ai_provider or get_ai_provider()
        self.storage = storage or get_storage_backend()

    # ---------- document lifecycle ----------

    async def list_documents(self, owner_id: uuid.UUID) -> list[KnowledgeDocument]:
        result = await self.db.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.owner_id == owner_id)
            .order_by(KnowledgeDocument.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_document(self, owner_id: uuid.UUID, document_id: uuid.UUID) -> KnowledgeDocument:
        result = await self.db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id, KnowledgeDocument.owner_id == owner_id
            )
        )
        document = result.scalar_one_or_none()
        if document is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge document not found")
        return document

    async def create_from_upload(
        self,
        owner: User,
        title: str,
        filename: str,
        source_type: KnowledgeSourceType,
        raw_content: bytes,
        agent_id: uuid.UUID | None = None,
    ) -> KnowledgeDocument:
        await enforce_knowledge_document_limit(self.db, owner.id)
        file_path = await self.storage.save(owner.id, filename, raw_content)
        document = KnowledgeDocument(
            owner_id=owner.id,
            agent_id=agent_id,
            title=title,
            source_type=source_type,
            file_path=file_path,
            status=KnowledgeStatus.PENDING,
        )
        self.db.add(document)
        await self.db.commit()
        await self.db.refresh(document)
        return document

    async def create_from_text(
        self,
        owner: User,
        title: str,
        content: str,
        source_type: KnowledgeSourceType = KnowledgeSourceType.TEXT,
        agent_id: uuid.UUID | None = None,
    ) -> KnowledgeDocument:
        await enforce_knowledge_document_limit(self.db, owner.id)
        file_path = await self.storage.save(owner.id, f"{title}.txt", content.encode("utf-8"))
        document = KnowledgeDocument(
            owner_id=owner.id,
            agent_id=agent_id,
            title=title,
            source_type=source_type,
            file_path=file_path,
            status=KnowledgeStatus.PENDING,
        )
        self.db.add(document)
        await self.db.commit()
        await self.db.refresh(document)
        return document

    async def create_from_url(
        self,
        owner: User,
        url: str,
        title: str | None,
        html: str,
        agent_id: uuid.UUID | None = None,
    ) -> KnowledgeDocument:
        await enforce_knowledge_document_limit(self.db, owner.id)
        document = KnowledgeDocument(
            owner_id=owner.id,
            agent_id=agent_id,
            title=title or url,
            source_type=KnowledgeSourceType.URL,
            source_url=url,
            status=KnowledgeStatus.PENDING,
        )
        self.db.add(document)
        await self.db.flush()

        # Stash the fetched HTML on disk too, so re-ingestion doesn't require re-fetching.
        file_path = await self.storage.save(owner.id, f"{document.id}.html", html.encode("utf-8"))
        document.file_path = file_path
        await self.db.commit()
        await self.db.refresh(document)
        return document

    async def delete_document(self, owner_id: uuid.UUID, document_id: uuid.UUID) -> None:
        document = await self.get_document(owner_id, document_id)
        if document.file_path:
            try:
                await self.storage.delete(document.file_path)
            except Exception:
                logger.warning("Failed to delete stored file for document %s", document.id, exc_info=True)
        await self.db.delete(document)  # cascades to chunks
        await self.db.commit()

    # ---------- ingestion pipeline ----------

    async def ingest_document(self, document: KnowledgeDocument) -> KnowledgeDocument:
        """Parses, chunks, embeds, and persists chunks for one document.
        Idempotent-ish: re-running deletes previously-created chunks first."""
        document.status = KnowledgeStatus.PROCESSING
        document.error_message = None
        await self.db.commit()

        try:
            raw_text = await self._extract_raw_text(document)
            chunks = chunk_text(raw_text)

            if not chunks:
                raise ExtractionError("Document produced no usable text after extraction/chunking.")

            vectors = await self.ai_provider.embed(chunks)

            # Clear any chunks from a previous ingestion attempt.
            existing = await self.db.execute(
                select(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
            )
            for old_chunk in existing.scalars().all():
                await self.db.delete(old_chunk)

            for index, (chunk_content, vector) in enumerate(zip(chunks, vectors)):
                self.db.add(
                    KnowledgeChunk(
                        document_id=document.id,
                        owner_id=document.owner_id,
                        chunk_index=index,
                        content=chunk_content,
                        embedding=vector,
                    )
                )

            document.status = KnowledgeStatus.READY
            await self.db.commit()
            await self.db.refresh(document)
            return document

        except Exception as exc:
            document.status = KnowledgeStatus.FAILED
            document.error_message = str(exc)[:2000]
            await self.db.commit()
            logger.error("Knowledge ingestion failed for document %s: %s", document.id, exc, exc_info=True)
            await NotificationService(self.db).create(
                owner_id=document.owner_id,
                type_=NotificationType.KNOWLEDGE_FAILED,
                title="Knowledge upload failed",
                body=f"'{document.title}' couldn't be processed: {str(exc)[:200]}",
                context={"document_id": str(document.id)},
            )
            return document

    async def _extract_raw_text(self, document: KnowledgeDocument) -> str:
        if document.file_path is None:
            raise ExtractionError("Document has no stored content to extract from.")

        raw = await self.storage.read(document.file_path)

        if document.source_type == KnowledgeSourceType.URL:
            return extract_text_from_html(raw.decode("utf-8"))

        return extract_text(document.source_type, raw)

    # ---------- search (RAG retrieval) ----------

    async def search(
        self,
        owner_id: uuid.UUID,
        query: str,
        agent_id: uuid.UUID | None = None,
        top_k: int = 5,
    ) -> list[tuple[KnowledgeChunk, float]]:
        """Returns (chunk, similarity_score) pairs, highest first.
        When agent_id is given, includes both that agent's private
        documents and shared (agent_id IS NULL) documents."""
        stmt = (
            select(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(KnowledgeChunk.owner_id == owner_id, KnowledgeDocument.status == KnowledgeStatus.READY)
            .options(selectinload(KnowledgeChunk.document))
        )
        if agent_id is not None:
            stmt = stmt.where(
                (KnowledgeDocument.agent_id == agent_id) | (KnowledgeDocument.agent_id.is_(None))
            )

        result = await self.db.execute(stmt)
        candidates = list(result.scalars().all())
        if not candidates:
            return []

        query_vector = (await self.ai_provider.embed([query]))[0]
        return top_k_by_similarity(query_vector, candidates, key=lambda c: c.embedding, k=top_k)
