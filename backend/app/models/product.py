"""Product model.

Products are embedded (name + description + category + price folded
into one string) exactly like knowledge chunks and memory entries, so
ProductService.search() reuses the same cosine-similarity pattern
(app/core/vector_math.py) as Knowledge/Memory search.

The Sales Agent can use Product.searchable_text() for semantic
retrieval and primary_image_url() for sending the actual catalog
image through channels such as WhatsApp.

Currency defaults to the business/application billing currency rather
than being hardcoded.
"""

import enum
import uuid
from decimal import Decimal
from typing import Any

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
                str(v.get("name", "")).strip()
                for v in self.variants
                if isinstance(v, dict) and v.get("name")
            )

            if variant_names:
                parts.append(
                    f"Available in: {variant_names}"
                )

        parts.append(
            f"Price: {self.price} {self.currency}"
        )

        return ". ".join(parts)

    def primary_image_url(self) -> str | None:
        """Return the first usable public product image URL.

        Supports the common formats currently used by product
        upload systems:

        1. String URL:
           ["https://example.com/image.jpg"]

        2. Object with `url`:
           [{"url": "https://example.com/image.jpg"}]

        3. Cloudinary-style object with `secure_url`:
           [{"secure_url": "https://res.cloudinary.com/..."}]

        4. Object with `src`:
           [{"src": "https://example.com/image.jpg"}]

        Returns None when no usable image exists.
        """

        if not isinstance(self.images, list):
            return None

        for image in self.images:
            if isinstance(image, str):
                url = image.strip()

                if url.startswith(("http://", "https://")):
                    return url

                continue

            if isinstance(image, dict):
                for key in ("secure_url", "url", "src"):
                    value = image.get(key)

                    if isinstance(value, str):
                        url = value.strip()

                        if url.startswith(("http://", "https://")):
                            return url

        return None

    def has_image(self) -> bool:
        """Return True when the product has a usable public image URL."""
        return self.primary_image_url() is not None

    def is_in_stock(self) -> bool:
        """Return whether the product currently has available inventory.

        A None inventory value is treated as unknown rather than
        automatically out of stock.
        """

        if self.inventory is None:
            return True

        return self.inventory > 0

    def available_variant_names(self) -> list[str]:
        """Return the names of configured product variants."""

        if not isinstance(self.variants, list):
            return []

        names: list[str] = []

        for variant in self.variants:
            if not isinstance(variant, dict):
                continue

            name = variant.get("name")

            if isinstance(name, str) and name.strip():
                names.append(name.strip())

        return names
