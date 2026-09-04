import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.order import DeliveryStatus, OrderStatus, PaymentStatus
from app.models.payment_method import PaymentMethodType


class OrderLineItemInput(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(ge=1)


class OrderCreate(BaseModel):
    customer_id: uuid.UUID
    items: list[OrderLineItemInput] = Field(min_length=1)
    payment_method_id: uuid.UUID | None = None
    notes: str | None = None
    recipient_name: str | None = None
    recipient_phone: str | None = None
    shipping_address: str | None = None


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


class OrderResponse(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    conversation_id: uuid.UUID | None
    payment_method_id: uuid.UUID | None
    items: list
    total_amount: Decimal
    currency: str
    status: OrderStatus
    payment_status: PaymentStatus
    delivery_status: DeliveryStatus
    notes: str | None
    receipt_file_id: str | None
    recipient_name: str | None
    recipient_phone: str | None
    shipping_address: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderEventResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaymentMethodCreate(BaseModel):
    method_type: PaymentMethodType
    label: str = Field(min_length=1, max_length=255)
    bank_name: str | None = None
    account_name: str | None = None
    account_number: str | None = None


class PaymentMethodUpdate(BaseModel):
    label: str | None = None
    is_enabled: bool | None = None
    bank_name: str | None = None
    account_name: str | None = None
    account_number: str | None = None


class PaymentMethodResponse(BaseModel):
    id: uuid.UUID
    method_type: PaymentMethodType
    label: str
    is_enabled: bool
    details: dict
    created_at: datetime


class CustomerResponse(BaseModel):
    id: uuid.UUID
    platform: str
    external_user_id: str
    display_name: str | None
    lifetime_spend: Decimal
    order_count: int
    last_interaction_at: datetime | None
    preferred_language: str | None
    preferred_payment_method: str | None
    interests: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}
