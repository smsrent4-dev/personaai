"""PaymentMethod model.

Each business configures one or more ways to accept payment. `details`
is a type-varying payload - bank name/account name/account number for
bank_transfer, empty for cash/pay_on_delivery - stored ENCRYPTED at
rest via app/core/crypto.py (same pattern as PlatformIntegration's bot
tokens and Subscription's card authorization), since bank account
details are exactly the kind of thing that shouldn't sit in plaintext.

Extensible by design per the spec: adding Paystack/Flutterwave/Stripe/
Moniepoint/Square later means adding a new PaymentMethodType value and
a details shape for it - this model and PaymentMethodService don't
need to change, only the payment-processing code that reads `details`
for that type.
"""
import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import decrypt_json, encrypt_json
from app.core.types import GUID
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PaymentMethodType(str, enum.Enum):
    BANK_TRANSFER = "bank_transfer"
    CASH = "cash"
    PAY_ON_DELIVERY = "pay_on_delivery"


class PaymentMethod(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "payment_methods"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    method_type: Mapped[PaymentMethodType] = mapped_column(
        Enum(PaymentMethodType, name="payment_method_type", values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    details_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)

    def get_details(self) -> dict:
        return decrypt_json(self.details_encrypted)

    def set_details(self, data: dict) -> None:
        self.details_encrypted = encrypt_json(data)

    def __repr__(self) -> str:
        return f"<PaymentMethod {self.method_type.value} owner={self.owner_id}>"
