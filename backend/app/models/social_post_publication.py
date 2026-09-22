"""Social post publication model.

Stores the result of publishing a SocialPost to a specific connected
platform integration.

One SocialPost can therefore have independent publication states:

    Telegram  -> published
    WhatsApp  -> failed

without losing the successful publication.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import GUID
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SocialPublicationPlatform(str, enum.Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"


class SocialPublicationStatus(str, enum.Enum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class SocialPostPublication(
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
):
    __tablename__ = "social_post_publications"

    __table_args__ = (
        UniqueConstraint(
            "social_post_id",
            "integration_id",
            name="uq_social_post_publication_integration",
        ),
    )

    social_post_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("social_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    integration_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("platform_integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    platform: Mapped[SocialPublicationPlatform] = mapped_column(
        Enum(
            SocialPublicationPlatform,
            name="social_publication_platform",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )

    status: Mapped[SocialPublicationStatus] = mapped_column(
        Enum(
            SocialPublicationStatus,
            name="social_publication_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=SocialPublicationStatus.PENDING,
        nullable=False,
        index=True,
    )

    external_post_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    social_post: Mapped["SocialPost"] = relationship(
        "SocialPost",
        back_populates="publications",
    )

    integration: Mapped["PlatformIntegration"] = relationship(
        "PlatformIntegration",
        lazy="joined",
    )

    def __repr__(self) -> str:
        return (
            f"<SocialPostPublication {self.id} "
            f"{self.platform.value}/{self.status.value}>"
        )