"""labour benchmarks can be set per vehicle class

Revision ID: c9d0e1f2a3b4
Revises: b7c8d9e0f1a2
"""
from alembic import op
import sqlalchemy as sa

revision = "c9d0e1f2a3b4"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reference_labour_benchmarks", sa.Column("vehicle_class", sa.String(30)))
    op.drop_constraint("uq_bench", "reference_labour_benchmarks", type_="unique")
    # NULL means "every vehicle"; COALESCE makes two such rows for the same code and source collide, as they should.
    op.execute("CREATE UNIQUE INDEX uq_bench ON reference_labour_benchmarks (client_id, vmrs_code, COALESCE(vehicle_class, ''), source)")


def downgrade() -> None:
    op.execute("DROP INDEX uq_bench")
    op.execute("DELETE FROM reference_labour_benchmarks WHERE vehicle_class IS NOT NULL")
    op.create_unique_constraint("uq_bench", "reference_labour_benchmarks", ["client_id", "vmrs_code", "source"])
    op.drop_column("reference_labour_benchmarks", "vehicle_class")
