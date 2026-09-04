"""ProductService - CRUD plus semantic search for the Sales Agent.

Products are scoped to their owner and support full CRUD operations.

The service is responsible for:

- Creating products.
- Updating product information.
- Updating inventory/status independently.
- Deleting products.
- Uploading/removing product images.
- Generating and refreshing semantic-search embeddings.
- Searching ACTIVE products for the Sales Agent.

Products are automatically activated after a successful embedding is
generated during creation.

When searchable product information changes, the embedding is regenerated.
Inventory-only changes do NOT require a new embedding because inventory
does not form part of searchable_text().
"""

import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.vector_math import top_k_by_similarity
from app.models.product import Product, ProductStatus, ProductType
from app.services.ai import AIProvider, get_ai_provider
from app.services.knowledge.storage import (
    StorageBackend,
    get_storage_backend,
)


_ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}

_MAX_IMAGE_SIZE = 10 * 1024 * 1024


class ProductService:
    def __init__(
        self,
        db: AsyncSession,
        ai_provider: AIProvider | None = None,
        storage: StorageBackend | None = None,
    ):
        self.db = db
        self.ai_provider = ai_provider or get_ai_provider()
        self.storage = storage or get_storage_backend()

    async def list_products(
        self,
        owner_id: uuid.UUID,
        status_filter: ProductStatus | None = None,
    ) -> list[Product]:
        """Return all products belonging to an owner.

        Products are returned regardless of inventory level.

        This is intentional. A product with inventory=0 must remain visible
        in the dashboard so the business owner can edit it, restock it,
        archive it, or delete it.

        When status_filter is supplied, only products with that status
        are returned.
        """
        stmt = select(Product).where(
            Product.owner_id == owner_id
        )

        if status_filter is not None:
            stmt = stmt.where(
                Product.status == status_filter
            )

        stmt = stmt.order_by(
            Product.created_at.desc()
        )

        result = await self.db.execute(stmt)

        return list(result.scalars().all())

    async def get_product(
        self,
        owner_id: uuid.UUID,
        product_id: uuid.UUID,
    ) -> Product:
        """Return a product scoped to its owner."""
        result = await self.db.execute(
            select(Product).where(
                Product.id == product_id,
                Product.owner_id == owner_id,
            )
        )

        product = result.scalar_one_or_none()

        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found",
            )

        return product

    async def create_product(
        self,
        owner_id: uuid.UUID,
        name: str,
        product_type: ProductType,
        price: Decimal,
        description: str | None = None,
        currency: str | None = None,
        discount_percent: float = 0.0,
        inventory: int | None = None,
        category: str | None = None,
        variants: list | None = None,
        images: list | None = None,
    ) -> Product:
        """Create and activate a product.

        Currency defaults to the application's configured billing currency
        instead of hardcoding USD.

        The product is embedded before it is committed to the database.
        Once embedding succeeds, the product is marked ACTIVE.

        If embedding fails, the transaction is rolled back and the product
        is not persisted.
        """
        product_currency = (
            currency or settings.DEFAULT_BILLING_CURRENCY
        ).upper()

        product = Product(
            owner_id=owner_id,
            name=name,
            description=description,
            product_type=product_type,
            price=price,
            currency=product_currency,
            discount_percent=discount_percent,
            inventory=inventory,
            category=category,
            variants=variants or [],
            images=images or [],
        )

        try:
            embedding = (
                await self.ai_provider.embed(
                    [product.searchable_text()]
                )
            )[0]

            product.embedding = embedding

            # A successfully embedded new product is searchable.
            product.status = ProductStatus.ACTIVE

            self.db.add(product)

            await self.db.commit()
            await self.db.refresh(product)

            return product

        except Exception:
            await self.db.rollback()
            raise

    async def update_product(
        self,
        owner_id: uuid.UUID,
        product_id: uuid.UUID,
        updates: dict,
    ) -> Product:
        """Update a product and refresh its embedding when required.

        Inventory and status can be changed independently.

        Examples:

        - inventory 0 -> 20: restock a product.
        - inventory 20 -> 0: mark it out of stock without deleting it.
        - status active -> archived: stop it from semantic search.
        - status archived -> active: make it searchable again.
        - price/name/description/category/variants/currency changes:
          regenerate the semantic embedding.

        Explicit status updates are respected. We do not automatically
        overwrite an owner's status choice.
        """
        product = await self.get_product(
            owner_id,
            product_id,
        )

        if not updates:
            return product

        text_fields = {
            "name",
            "description",
            "category",
            "price",
            "currency",
            "variants",
        }

        needs_reembed = bool(
            text_fields.intersection(updates.keys())
        )

        # Normalize currency before storing it.
        if "currency" in updates and updates["currency"] is not None:
            updates["currency"] = updates["currency"].upper()

        # Apply requested changes.
        for field, value in updates.items():
            setattr(product, field, value)

        try:
            if needs_reembed:
                embedding = (
                    await self.ai_provider.embed(
                        [product.searchable_text()]
                    )
                )[0]

                product.embedding = embedding

                # Only automatically reactivate when the caller did not
                # explicitly provide a status.
                #
                # This means editing price/name/etc. does not accidentally
                # archive a product, while an explicit status=ARCHIVED or
                # status=DRAFT is still respected.
                if "status" not in updates:
                    product.status = ProductStatus.ACTIVE

            await self.db.commit()
            await self.db.refresh(product)

            return product

        except Exception:
            await self.db.rollback()
            raise

    async def delete_product(
        self,
        owner_id: uuid.UUID,
        product_id: uuid.UUID,
    ) -> None:
        """Permanently delete a product belonging to an owner."""
        product = await self.get_product(
            owner_id,
            product_id,
        )

        await self.db.delete(product)
        await self.db.commit()

    async def add_image(
        self,
        owner_id: uuid.UUID,
        product_id: uuid.UUID,
        filename: str,
        content: bytes,
        content_type: str | None,
    ) -> Product:
        """Upload a product image and append its public URL.

        The stored URL is designed to be usable by Telegram/WhatsApp
        when the Sales Agent sends the matching product image to a
        customer.

        Image uploads do not change the semantic embedding because images
        are not currently included in searchable_text().
        """
        if content_type not in _ALLOWED_IMAGE_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Unsupported image type '{content_type}'. "
                    "Use JPEG, PNG, WEBP, or GIF."
                ),
            )

        if len(content) > _MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Image must be under 10MB.",
            )

        product = await self.get_product(
            owner_id,
            product_id,
        )

        stored_path = await self.storage.save(
            owner_id,
            filename,
            content,
        )

        public_url = (
            f"{settings.API_BASE_URL}"
            f"/api/v1/products/images/{stored_path}"
        )

        current_images = product.images or []

        product.images = [
            *current_images,
            public_url,
        ]

        await self.db.commit()
        await self.db.refresh(product)

        return product

    async def remove_image(
        self,
        owner_id: uuid.UUID,
        product_id: uuid.UUID,
        image_url: str,
    ) -> Product:
        """Remove an image URL from a product."""
        product = await self.get_product(
            owner_id,
            product_id,
        )

        current_images = product.images or []

        product.images = [
            url
            for url in current_images
            if url != image_url
        ]

        await self.db.commit()
        await self.db.refresh(product)

        return product

    async def search(
        self,
        owner_id: uuid.UUID,
        query: str,
        top_k: int = 5,
    ) -> list[tuple[Product, float]]:
        """Semantic-search ACTIVE products belonging to an owner.

        Products without embeddings are ignored because they cannot
        participate in cosine-similarity ranking.

        Inventory is intentionally NOT checked here.

        A product with inventory=0 can still be retrieved by the Sales
        Agent so the agent can tell the customer that the product is
        currently out of stock instead of behaving as though the product
        does not exist.

        Archived/draft products are excluded because only ACTIVE products
        are intended to be customer-facing/searchable.
        """
        result = await self.db.execute(
            select(Product).where(
                Product.owner_id == owner_id,
                Product.status == ProductStatus.ACTIVE,
            )
        )

        candidates = [
            product
            for product in result.scalars().all()
            if product.embedding is not None
        ]

        if not candidates:
            return []

        query_vector = (
            await self.ai_provider.embed([query])
        )[0]

        return top_k_by_similarity(
            query_vector,
            candidates,
            key=lambda product: product.embedding,
            k=top_k,
        )