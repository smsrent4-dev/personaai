import mimetypes
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.product import ProductStatus
from app.models.user import User
from app.schemas.product import (
    ProductCreate,
    ProductResponse,
    ProductSearchRequest,
    ProductSearchResponse,
    ProductSearchResult,
    ProductUpdate,
)
from app.services.product_service import ProductService
from app.services.knowledge.storage import get_storage_backend

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("", response_model=list[ProductResponse])
async def list_products(
    product_status: ProductStatus | None = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ProductService(db).list_products(current_user.id, status_filter=product_status)


# Registered before GET /{product_id} deliberately: both are GET routes
# under this prefix, and FastAPI/Starlette match routes in registration
# order — a "images" path segment would otherwise get swallowed by
# /{product_id} first (and fail UUID parsing with a 422) rather than
# ever reaching this handler.
@router.get("/images/{file_path:path}")
async def get_product_image(file_path: str):
    """Publicly servable — deliberately NOT behind get_current_active_user.
    Telegram/WhatsApp's own servers fetch this URL directly when
    MessagingPipeline sends a matched product's photo back to a
    customer (see its docstring); they don't have, and can't be given,
    a PersonaAI JWT. Low sensitivity by design: these are catalog
    photos meant to be shown to any customer who messages the bot,
    not private data — same posture as any e-commerce site's public
    product images. Path traversal is guarded by
    LocalStorageBackend._resolve(), which this reuses rather than
    re-implementing.
    """
    storage = get_storage_backend()
    try:
        content = await storage.read(file_path)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found") from exc

    content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    return Response(content=content, media_type=content_type)


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ProductService(db).create_product(
        owner_id=current_user.id,
        name=data.name,
        product_type=data.product_type,
        price=data.price,
        description=data.description,
        currency=data.currency,
        discount_percent=data.discount_percent,
        inventory=data.inventory,
        category=data.category,
        variants=[v.model_dump() for v in data.variants],
        images=data.images,
    )


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ProductService(db).get_product(current_user.id, product_id)


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID,
    data: ProductUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    updates = data.model_dump(exclude_unset=True)
    if "variants" in updates and updates["variants"] is not None:
        updates["variants"] = [v if isinstance(v, dict) else v.model_dump() for v in updates["variants"]]
    return await ProductService(db).update_product(current_user.id, product_id, updates)


@router.post("/{product_id}/images", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def upload_product_image(
    product_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """What lets a business actually attach a real photo to a product —
    see ProductService.add_image's docstring for how it becomes the
    image MessagingPipeline sends back when a customer's message
    matches this product."""
    content = await file.read()
    return await ProductService(db).add_image(
        current_user.id, product_id, file.filename or "image", content, file.content_type
    )


@router.delete("/{product_id}/images", response_model=ProductResponse)
async def remove_product_image(
    product_id: uuid.UUID,
    image_url: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ProductService(db).remove_image(current_user.id, product_id, image_url)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await ProductService(db).delete_product(current_user.id, product_id)


@router.post("/search", response_model=ProductSearchResponse)
async def search_products(
    data: ProductSearchRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    results = await ProductService(db).search(current_user.id, data.query, top_k=data.top_k)
    return ProductSearchResponse(
        results=[ProductSearchResult(product=product, score=score) for product, score in results]
    )
