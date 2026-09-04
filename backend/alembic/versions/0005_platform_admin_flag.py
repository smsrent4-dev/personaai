"""add is_platform_admin flag to users

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("is_platform_admin", sa.Boolean, nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    op.drop_column("users", "is_platform_admin")
