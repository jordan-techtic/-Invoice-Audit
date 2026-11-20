"""reference data: vehicle class/year/make/model/odometer, warranty 'covers'

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
"""
from alembic import op
import sqlalchemy as sa

revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("vehicle_class", sa.String(30)))
    op.add_column("vehicles", sa.Column("year", sa.Integer))
    op.add_column("vehicles", sa.Column("make", sa.String(60)))
    op.add_column("vehicles", sa.Column("model", sa.String(80)))
    op.add_column("vehicles", sa.Column("start_odometer", sa.Integer))
    op.add_column("warranty_rules", sa.Column("covers", sa.String(12), nullable=False, server_default="parts+labour"))


def downgrade() -> None:
    op.drop_column("warranty_rules", "covers")
    for c in ("start_odometer", "model", "make", "year", "vehicle_class"):
        op.drop_column("vehicles", c)
