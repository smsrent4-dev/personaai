"""Base interface for social media publishers.

Social publishers are responsible only for taking already-created
SocialPost content and publishing it to a specific platform.

Database state and publication tracking remain in SocialPostService.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class SocialPublisherError(Exception):
    """Base exception for social publishing failures."""


class SocialPublisherConfigurationError(SocialPublisherError):
    """Raised when a platform integration is not configured correctly."""


class SocialPublisherPermissionError(SocialPublisherError):
    """Raised when the integration lacks the required platform permission."""


class SocialPublisherMediaError(SocialPublisherError):
    """Raised when the supplied media cannot be published."""


@dataclass(slots=True)
class SocialPublishResult:
    """Result returned after successfully publishing content."""

    external_post_id: str | None = None


class SocialPublisher(ABC):
    """Interface implemented by every social publishing platform."""

    platform_name: str = "base"

    @abstractmethod
    async def publish(
        self,
        *,
        media_url: str,
        media_type: str,
        caption: str | None = None,
    ) -> SocialPublishResult:
        """Publish content and return its external platform ID."""

        raise NotImplementedError

    async def delete(
        self,
        *,
        external_post_id: str,
    ) -> None:
        """Delete previously published content when supported."""

        raise SocialPublisherError(
            f"{self.platform_name} does not support deleting "
            "published content."
        )

    async def edit(
        self,
        *,
        external_post_id: str,
        media_url: str | None = None,
        caption: str | None = None,
    ) -> SocialPublishResult:
        """Edit previously published content when supported."""

        raise SocialPublisherError(
            f"{self.platform_name} does not support editing "
            "published content."
        )