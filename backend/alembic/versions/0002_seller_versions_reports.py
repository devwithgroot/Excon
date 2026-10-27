"""Seller approved profiles, versions, and lead reports.

Revision ID: 0002_seller_versions_reports
Revises: 0001_research_tables
Create Date: 2026-10-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_seller_versions_reports"
down_revision: Union[str, Sequence[str], None] = "0001_research_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sellers", sa.Column("approved_profile", sa.JSON(), nullable=True))
    op.add_column(
        "sellers",
        sa.Column("approved_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sellers",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
    )
    op.create_table(
        "seller_profile_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("seller_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_seller_profile_versions_seller_id", "seller_profile_versions", ["seller_id"]
    )
    op.create_table(
        "lead_reports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("seller_id", sa.String(length=36), nullable=True),
        sa.Column("seller_version", sa.Integer(), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("recommendation", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("run_id", name="uq_lead_reports_run_id"),
    )


def downgrade() -> None:
    op.drop_table("lead_reports")
    op.drop_index("ix_seller_profile_versions_seller_id", table_name="seller_profile_versions")
    op.drop_table("seller_profile_versions")
    op.drop_column("sellers", "status")
    op.drop_column("sellers", "approved_version")
    op.drop_column("sellers", "approved_profile")
