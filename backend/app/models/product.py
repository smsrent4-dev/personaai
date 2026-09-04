"""Product model.

Products are embedded (name + description + category + price folded
into one string) exactly like knowledge chunks and memory entries, so
ProductService.search() reuses the same cosine-similarity pattern
(app/core/vector_math.py) as Knowledge/Memory search. This is what
lets the Sales Agent "automatically retrieve product information"
(per the original spec) without any hardcoded product-lookup logic -
see MessagingPipeline._build_reply in app/services/messaging_pipeline.py.

Currency defaults to the business/application billing currency rather
than being hardcoded. This keeps product creation consistent with
settings.DEFAULT_BILLING_CURRENCY (for example, NGN for Nigerian
businesses).
"""

import enum
import uuid
from decimal import Decimal

from sqlalchemy import JSON, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.core.types import GUID, Embedding
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProductType(str, enum.Enum):
    PHYSICAL = "physical"
    DIGITAL = "digital"
    SERVICE = "service"


class ProductStatus(str, enum.Enum):
    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"


class Product(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "products"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    product_type: Mapped[ProductType] = mapped_column(
        Enum(
            ProductType,
            name="product_type",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )

    price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        default=lambda: settings.DEFAULT_BILLING_CURRENCY,
        nullable=False,
    )

    discount_percent: Mapped[float] = mapped_column(
        default=0.0,
        nullable=False,
    )

    inventory: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    category: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    variants: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )

    images: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )

    status: Mapped[ProductStatus] = mapped_column(
        Enum(
            ProductStatus,
            name="product_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=ProductStatus.DRAFT,
        nullable=False,
    )

    embedding: Mapped[list[float] | None] = mapped_column(
        Embedding(settings.EMBEDDING_DIMENSIONS),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<Product {self.name!r} {self.price} {self.currency}>"

    def searchable_text(self) -> str:
        """Build the text representation used for semantic search."""
        parts = [self.name]

        if self.category:
            parts.append(f"Category: {self.category}")

        if self.description:
            parts.append(self.description)

        if self.variants:
            variant_names = ", ".join(
                v.get("name", "")
                for v in self.variants
                if v.get("name")
            )

            if variant_names:
                parts.append(
                    f"Available in: {variant_names}"
                )

        parts.append(
            f"Price: {self.price} {self.currency}"
        )

        return ". ".join(parts)