"""PlatformBootstrap — a single-row table whose only job is to make
"promote whoever calls /admin/bootstrap first" race-proof.

The naive version of that check (count existing admins, and if zero,
promote the caller) is a classic check-then-act race: two concurrent
requests can both read "zero admins exist" before either has
committed, and both succeed — an attacker racing the legitimate first
admin at signup/launch time can end up with an unauthorized platform-
admin account. Counting rows is never atomic against a second
transaction doing the same count; only a write with a uniqueness
constraint the database itself enforces is.

The fix: bootstrap first tries to INSERT a row with a fixed primary
key (id=1). Primary-key uniqueness is enforced atomically by every
database engine (Postgres and SQLite alike, unlike a bespoke
dialect-specific "INSERT ... ON CONFLICT" — this needs no dialect-
specific SQL). Exactly one concurrent request's INSERT can succeed;
every other one gets an IntegrityError and is told someone already
claimed it. See AdminService.bootstrap_first_admin.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.types import GUID
from app.database import Base


class PlatformBootstrap(Base):
    __tablename__ = "platform_bootstrap"

    # Always inserted as 1 — there is, and only ever will be, one row.
    id: Mapped[int] = mapped_column(primary_key=True)
    admin_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
