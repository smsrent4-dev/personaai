"""OrderEvent - the "Timeline" from the spec: one row per status change
on an order, so the history is queryable/displayable rather than
reconstructed from updated_at timestamps alone.
"""
import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.types import GUID
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class OrderEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "order_events"

    order_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
