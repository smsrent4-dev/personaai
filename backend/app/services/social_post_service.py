"""Social post business logic.

This service is platform-independent.

It is responsible for:
- creating social posts
- validating connected integrations
- creating per-platform publication records
- retrieving posts
- deleting posts
- updating publication state
- calculating the overall post status

Actual Telegram/WhatsApp publishing belongs to the platform publisher
classes and should be called by the worker layer.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import PlatformIntegration
from app.models.platform_enums import Platform
from app.models.social_post import (
    SocialMediaType,
    SocialPost,
    SocialPostStatus,
)
from app.models.social_post_publication import (
    SocialPostPublication,
    SocialPublicationPlatform,
    SocialPublicationStatus,
)


class SocialPostService:
    """Business logic for social posts."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # CREATE
    # ------------------------------------------------------------------

    async def create_post(
        self,
        *,
        owner_id: uuid.UUID,
        caption: str | None,
        media_url: str,
        media_type: SocialMediaType,
        integration_ids: list[uuid.UUID],
    ) -> SocialPost:
        """Create a social post and its platform publication records."""

        if not integration_ids:
            raise ValueError(
                "At least one platform integration is required."
            )

        # Remove duplicates while preserving order.
        unique_integration_ids = list(dict.fromkeys(integration_ids))

        result = await self.db.execute(
            select(PlatformIntegration).where(
                PlatformIntegration.id.in_(unique_integration_ids),
                PlatformIntegration.owner_id == owner_id,
            )
        )

        integrations = result.scalars().all()

        found_ids = {integration.id for integration in integrations}

        missing_ids = [
            integration_id
            for integration_id in unique_integration_ids
            if integration_id not in found_ids
        ]

        if missing_ids:
            raise ValueError(
                "One or more selected integrations do not belong "
                "to this account."
            )

        supported_platforms = {
            Platform.TELEGRAM,
            Platform.WHATSAPP,
        }

        unsupported = [
            integration.platform
            for integration in integrations
            if integration.platform not in supported_platforms
        ]

        if unsupported:
            raise ValueError(
                "One or more selected integrations do not support "
                "social publishing."
            )

        post = SocialPost(
            owner_id=owner_id,
            caption=caption,
            media_url=media_url,
            media_type=media_type,
            status=SocialPostStatus.DRAFT,
        )

        self.db.add(post)

        await self.db.flush()

        for integration in integrations:
            platform = self._publication_platform(
                integration.platform
            )

            publication = SocialPostPublication(
                social_post_id=post.id,
                integration_id=integration.id,
                platform=platform,
                status=SocialPublicationStatus.PENDING,
            )

            self.db.add(publication)

        await self.db.commit()

        await self.db.refresh(post)

        return post

    # ------------------------------------------------------------------
    # GET
    # ------------------------------------------------------------------

    async def get_post(
        self,
        *,
        owner_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> SocialPost | None:
        """Get one social post belonging to the owner."""

        result = await self.db.execute(
            select(SocialPost)
            .where(
                SocialPost.id == post_id,
                SocialPost.owner_id == owner_id,
            )
        )

        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # LIST
    # ------------------------------------------------------------------

    async def list_posts(
        self,
        *,
        owner_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SocialPost]:
        """Return the owner's social posts."""

        limit = max(1, min(limit, 100))
        offset = max(0, offset)

        result = await self.db.execute(
            select(SocialPost)
            .where(
                SocialPost.owner_id == owner_id,
            )
            .order_by(
                SocialPost.created_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )

        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------

    async def delete_post(
        self,
        *,
        owner_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> bool:
        """Delete a social post belonging to the owner."""

        post = await self.get_post(
            owner_id=owner_id,
            post_id=post_id,
        )

        if post is None:
            return False

        await self.db.delete(post)
        await self.db.commit()

        return True

    # ------------------------------------------------------------------
    # PUBLISHING STATE
    # ------------------------------------------------------------------

    async def mark_post_publishing(
        self,
        *,
        owner_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> SocialPost:
        """Mark a post as currently being published."""

        post = await self._require_post(
            owner_id=owner_id,
            post_id=post_id,
        )

        post.status = SocialPostStatus.PUBLISHING

        await self.db.commit()
        await self.db.refresh(post)

        return post

    async def mark_publication_publishing(
        self,
        *,
        publication_id: uuid.UUID,
    ) -> SocialPostPublication:
        """Mark one platform publication as currently publishing."""

        publication = await self._require_publication(
            publication_id
        )

        publication.status = SocialPublicationStatus.PUBLISHING

        await self.db.commit()
        await self.db.refresh(publication)

        return publication

    # ------------------------------------------------------------------
    # PUBLICATION SUCCESS
    # ------------------------------------------------------------------

    async def mark_publication_published(
        self,
        *,
        publication_id: uuid.UUID,
        external_post_id: str | None = None,
    ) -> SocialPostPublication:
        """Mark one platform publication as successful."""

        publication = await self._require_publication(
            publication_id
        )

        publication.status = SocialPublicationStatus.PUBLISHED
        publication.external_post_id = external_post_id
        publication.published_at = datetime.now(timezone.utc)

        await self.db.flush()

        await self._refresh_parent_post_status(
            publication.social_post_id
        )

        await self.db.commit()
        await self.db.refresh(publication)

        return publication

    # ------------------------------------------------------------------
    # PUBLICATION FAILURE
    # ------------------------------------------------------------------

    async def mark_publication_failed(
        self,
        *,
        publication_id: uuid.UUID,
        error_message: str,
    ) -> SocialPostPublication:
        """Mark one platform publication as failed."""

        publication = await self._require_publication(
            publication_id
        )

        publication.status = SocialPublicationStatus.FAILED
        publication.error_message = error_message[:5000]

        await self.db.flush()

        await self._refresh_parent_post_status(
            publication.social_post_id
        )

        await self.db.commit()
        await self.db.refresh(publication)

        return publication

    # ------------------------------------------------------------------
    # REFRESH OVERALL POST STATUS
    # ------------------------------------------------------------------

    async def refresh_post_status(
        self,
        *,
        post_id: uuid.UUID,
    ) -> SocialPost:
        """Recalculate the overall status from platform publications."""

        post = await self._require_post_by_id(post_id)

        await self._refresh_parent_post_status(post.id)

        await self.db.commit()
        await self.db.refresh(post)

        return post

    async def _refresh_parent_post_status(
        self,
        post_id: uuid.UUID,
    ) -> None:
        """Calculate SocialPost status from its publications."""

        result = await self.db.execute(
            select(SocialPostPublication).where(
                SocialPostPublication.social_post_id == post_id
            )
        )

        publications = list(result.scalars().all())

        post = await self._require_post_by_id(post_id)

        if not publications:
            post.status = SocialPostStatus.DRAFT
            return

        statuses = {
            publication.status
            for publication in publications
        }

        published_count = sum(
            publication.status
            == SocialPublicationStatus.PUBLISHED
            for publication in publications
        )

        failed_count = sum(
            publication.status
            == SocialPublicationStatus.FAILED
            for publication in publications
        )

        total_count = len(publications)

        # Every platform succeeded.
        if published_count == total_count:
            post.status = SocialPostStatus.PUBLISHED

            if post.published_at is None:
                post.published_at = datetime.now(timezone.utc)

            return

        # At least one platform succeeded but another failed.
        if published_count > 0 and failed_count > 0:
            post.status = SocialPostStatus.PARTIALLY_PUBLISHED
            return

        # Every platform failed.
        if failed_count == total_count:
            post.status = SocialPostStatus.FAILED
            return

        # Some platforms are still pending/publishing.
        if (
            SocialPublicationStatus.PENDING in statuses
            or SocialPublicationStatus.PUBLISHING in statuses
        ):
            post.status = SocialPostStatus.PUBLISHING
            return

        post.status = SocialPostStatus.FAILED

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    async def _require_post(
        self,
        *,
        owner_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> SocialPost:
        post = await self.get_post(
            owner_id=owner_id,
            post_id=post_id,
        )

        if post is None:
            raise ValueError("Social post not found.")

        return post

    async def _require_post_by_id(
        self,
        post_id: uuid.UUID,
    ) -> SocialPost:
        result = await self.db.execute(
            select(SocialPost).where(
                SocialPost.id == post_id,
            )
        )

        post = result.scalar_one_or_none()

        if post is None:
            raise ValueError("Social post not found.")

        return post

    async def _require_publication(
        self,
        publication_id: uuid.UUID,
    ) -> SocialPostPublication:
        result = await self.db.execute(
            select(SocialPostPublication).where(
                SocialPostPublication.id == publication_id,
            )
        )

        publication = result.scalar_one_or_none()

        if publication is None:
            raise ValueError(
                "Social post publication not found."
            )

        return publication

    @staticmethod
    def _publication_platform(
        platform: Platform,
    ) -> SocialPublicationPlatform:
        """Convert integration platform enum to publication enum."""

        if platform == Platform.TELEGRAM:
            return SocialPublicationPlatform.TELEGRAM

        if platform == Platform.WHATSAPP:
            return SocialPublicationPlatform.WHATSAPP

        raise ValueError(
            f"Unsupported social publishing platform: {platform}"
        )