"""Photograph bytes shared by the API and worker.

Revision ID: 20261102_0002
Revises: 20261101_0001
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op

revision = "20261102_0002"
down_revision = "20261101_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "stored_objects" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "stored_objects",
        sa.Column("path", sa.String(length=500), primary_key=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("stored_objects")
