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
Product images are stored through the configured StorageBackend.
In production this can be Cloudinary, while local filesystem storage
remains available for development.
Products are automatically activated after a successful embedding is
generated during creation.
When searchable product information changes, the embedding is regenerated.
Inventory-only changes do NOT require a new embedding because inventory
does not form part of searchable_text().
"""
from __future__ import annotations
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
    # ------------------------------------------------------------------
    # products
    # ------------------------------------------------------------------
    async def list_products(
        self,
        owner_id: uuid.UUID,
        status_filter: ProductStatus | None = None,
    ) -> list[Product]:
        """Return all products belonging to an owner.
        Products are returned regardless of inventory level.
        A product with inventory=0 must remain visible in the dashboard
        so the business owner can edit it, restock it, archive it, or
        delete it.
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
        Currency defaults to the application's configured billing
        currency.
        The product is embedded before being committed to the database.
        If embedding fails, the transaction is rolled back and the
        product is not persisted.
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
            # A successfully embedded product is searchable.
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
        Explicit status updates are respected.
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
        if (
            "currency" in updates
            and updates["currency"] is not None
        ):
            updates["currency"] = (
                updates["currency"]
                .upper()
            )
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
                # Do not overwrite an explicitly supplied status.
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
        """Permanently delete a product and its stored images.
        Image deletion is attempted before the database row is removed.
        If an individual image cannot be deleted from external storage,
        the database deletion is aborted so we do not silently lose the
        storage reference.
        """
        product = await self.get_product(
            owner_id,
            product_id,
        )
        current_images = list(
            product.images or []
        )
        try:
            # Delete product images from the configured storage backend.
            for image_url in current_images:
                if not image_url:
                    continue
                await self.storage.delete(
                    image_url
                )
            await self.db.delete(product)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
    # ------------------------------------------------------------------
    # product images
    # ------------------------------------------------------------------
    async def add_image(
        self,
        owner_id: uuid.UUID,
        product_id: uuid.UUID,
        filename: str,
        content: bytes,
        content_type: str | None,
    ) -> Product:
        """Upload a product image through the configured storage backend.
        With Cloudinary enabled, storage.save() returns the Cloudinary
        secure HTTPS URL directly.
        That URL is stored in Product.images and can be passed directly
        to Telegram, WhatsApp, the frontend, or other integrations.
        Image uploads do not change the semantic embedding because images
        are not currently included in searchable_text().
        """
        normalized_content_type = (
            content_type.lower().split(";", 1)[0].strip()
            if content_type
            else None
        )
        if (
            normalized_content_type
            not in _ALLOWED_IMAGE_CONTENT_TYPES
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Unsupported image type "
                    f"'{content_type}'. "
                    "Use JPEG, PNG, WEBP, or GIF."
                ),
            )
        if len(content) > _MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Image must be under 10MB.",
            )
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Image file is empty.",
            )
        product = await self.get_product(
            owner_id,
            product_id,
        )
        try:
            stored_reference = (
                await self.storage.save(
                    owner_id,
                    filename,
                    content,
                )
            )
            # Cloudinary returns a complete secure HTTPS URL.
            #
            # LocalStorageBackend returns a relative filesystem path,
            # so get_url() is used when available.
            public_url = (
                await self.storage.get_url(
                    stored_reference
                )
            )
            if not public_url:
                # Local storage is retained for development.
                #
                # The application route can serve this relative path.
                public_url = (
                    f"{settings.API_BASE_URL.rstrip('/')}"
                    f"/api/v1/products/images/"
                    f"{stored_reference}"
                )
            current_images = list(
                product.images or []
            )
            product.images = [
                *current_images,
                public_url,
            ]
            await self.db.commit()
            await self.db.refresh(product)
            return product
        except Exception:
            await self.db.rollback()
            raise
    async def remove_image(
        self,
        owner_id: uuid.UUID,
        product_id: uuid.UUID,
        image_url: str,
    ) -> Product:
        """Remove an image from a product and from external storage."""
        product = await self.get_product(
            owner_id,
            product_id,
        )
        current_images = list(
            product.images or []
        )
        if image_url not in current_images:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product image not found.",
            )
        try:
            # Delete the actual file first.
            await self.storage.delete(
                image_url
            )
            # Then remove its reference from the product.
            product.images = [
                url
                for url in current_images
                if url != image_url
            ]
            await self.db.commit()
            await self.db.refresh(product)
            return product
        except Exception:
            await self.db.rollback()
            raise
    # ------------------------------------------------------------------
    # semantic search
    # ------------------------------------------------------------------
    async def search(
        self,
        owner_id: uuid.UUID,
        query: str,
        top_k: int = 5,
    ) -> list[tuple[Product, float]]:
        """Semantic-search ACTIVE products belonging to an owner.
        Products without embeddings are ignored.
        Inventory is intentionally NOT checked here.
        A product with inventory=0 can still be retrieved so the Sales
        Agent can tell the customer that the product is currently out
        of stock.
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
            await self.ai_provider.embed(
                [query]
            )
        )[0]
        return top_k_by_similarity(
            query_vector,
            candidates,
            key=lambda product: product.embedding,
            k=top_k,
        )
