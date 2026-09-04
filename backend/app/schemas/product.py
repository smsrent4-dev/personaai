import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field
from app.config import settings
from app.models.product import ProductStatus, ProductType


class ProductVariant(BaseModel):
    name: str
    price_delta: float = 0.0
    sku: str | None = None


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    product_type: ProductType
    price: Decimal = Field(ge=0)
    currency: str = Field(
    default=settings.DEFAULT_BILLING_CURRENCY,
    min_length=3,
    max_length=3,
)
    discount_percent: float = Field(default=0.0, ge=0, le=100)
    inventory: int | None = Field(default=None, ge=0)
    category: str | None = None
    variants: list[ProductVariant] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    discount_percent: float | None = Field(default=None, ge=0, le=100)
    inventory: int | None = Field(default=None, ge=0)
    category: str | None = None
    variants: list[ProductVariant] | None = None
    images: list[str] | None = None
    status: ProductStatus | None = None


class ProductResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    product_type: ProductType
    price: Decimal
    currency: str
    discount_percent: float
    inventory: int | None
    category: str | None
    variants: list
    images: list
    status: ProductStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProductSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)


class ProductSearchResult(BaseModel):
    product: ProductResponse
    score: float


class ProductSearchResponse(BaseModel):
    results: list[ProductSearchResult]
