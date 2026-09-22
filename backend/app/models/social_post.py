"""Social post model.

A SocialPost represents one piece of content created by a business owner
for publication to one or more connected social/messaging platforms.

The post itself is platform-independent. Platform-specific publication
results are stored in SocialPostPublication.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import GUID
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SocialPostStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    PARTIALLY_PUBLISHED = "partially_published"
    FAILED = "failed"


class SocialMediaType(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"


class SocialPost(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "social_posts"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    caption: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    media_url: Mapped[str] = mapped_column(
        String(2000),
        nullable=False,
    )

    media_type: Mapped[SocialMediaType] = mapped_column(
        Enum(
            SocialMediaType,
            name="social_media_type",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )

    status: Mapped[SocialPostStatus] = mapped_column(
        Enum(
            SocialPostStatus,
            name="social_post_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=SocialPostStatus.DRAFT,
        nullable=False,
        index=True,
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    publications: Mapped[list["SocialPostPublication"]] = relationship(
        "SocialPostPublication",
        back_populates="social_post",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<SocialPost {self.id} "
            f"{self.status.value} "
            f"{self.media_type.value}>"
        )