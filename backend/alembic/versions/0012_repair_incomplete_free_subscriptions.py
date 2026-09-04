"""repair incomplete free-plan subscriptions

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-08

Companion to the fix in SubscriptionService.start_checkout: before that
fix, starting checkout on a free (₦0) plan — including your own
current plan, since the frontend used to let you click "Subscribe" on
it — unconditionally set the subscription to INCOMPLETE before
Paystack was even involved, then never had anything to actually
confirm (there's nothing to charge on a ₦0 plan), leaving the account
stuck showing "waiting for payment confirmation" on a plan that was
never supposed to need any payment at all.

This is a narrow, safe, one-time repair: any subscription currently
INCOMPLETE whose plan price is exactly 0 gets flipped back to ACTIVE.
It does NOT touch incomplete subscriptions on any paid plan — those are
genuinely, correctly waiting on a real payment, and this migration
has no way to know whether that payment actually went through.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE subscriptions
        SET status = 'active'
        WHERE status = 'incomplete'
          AND plan_id IN (SELECT id FROM billing_plans WHERE price_amount = 0)
        """
    )


def downgrade() -> None:
    # Deliberately a no-op: there's no record of which rows this
    # migration touched, so there's nothing safe to revert them to.
    pass
