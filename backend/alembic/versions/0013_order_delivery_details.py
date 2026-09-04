"""order delivery details (recipient name/phone/shipping address)

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-09

Nothing on Order previously captured where a physical order should
actually be delivered — see app/models/order.py's docstring and
app/services/tools/create_order_tool.py for the enforcement this
enables (a physical-item order can't be created by the AI without
these, going forward).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("recipient_name", sa.String(255), nullable=True))
    op.add_column("orders", sa.Column("recipient_phone", sa.String(50), nullable=True))
    op.add_column("orders", sa.Column("shipping_address", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "shipping_address")
    op.drop_column("orders", "recipient_phone")
    op.drop_column("orders", "recipient_name")
