"""Import every model here so Base.metadata is complete for Alembic
autogenerate and for Base.metadata.create_all() in tests."""
from app.models.agent import Agent  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.billing_event import BillingEvent  # noqa: F401
from app.models.billing_plan import BillingPlan  # noqa: F401
from app.models.conversation import Conversation  # noqa: F401
from app.models.customer import Customer  # noqa: F401
from app.models.integration import PlatformIntegration  # noqa: F401
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument  # noqa: F401
from app.models.memory import MemoryEntry  # noqa: F401
from app.models.message import Message  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.order import Order  # noqa: F401
from app.models.order_event import OrderEvent  # noqa: F401
from app.models.payment_method import PaymentMethod  # noqa: F401
from app.models.platform_bootstrap import PlatformBootstrap  # noqa: F401
from app.models.product import Product  # noqa: F401
from app.models.refresh_token import RefreshToken  # noqa: F401
from app.models.subscription import Subscription  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.verification_token import VerificationToken  # noqa: F401
from app.models.whatsapp_profile import WhatsAppBusinessProfile  # noqa: F401

from app.models.social_post import (  # noqa: F401
    SocialMediaType,
    SocialPost,
    SocialPostStatus,
)

from app.models.social_post_publication import (  # noqa: F401
    SocialPostPublication,
    SocialPublicationPlatform,
    SocialPublicationStatus,
)