"""Create sellers, leads, research_runs, and evidence_items.

Revision ID: 0001_research_tables
Revises:
Create Date: 2026-10-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_research_tables"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sellers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("website_url", sa.String(length=500), nullable=True),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sellers_company_name", "sellers", ["company_name"])

    op.create_table(
        "leads",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("website_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "research_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("seller_id", sa.String(length=36), nullable=True),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("collected", sa.JSON(), nullable=False),
        sa.Column("missing", sa.JSON(), nullable=False),
        sa.Column("tools_used", sa.JSON(), nullable=False),
        sa.Column("gap_decisions", sa.JSON(), nullable=False),
        sa.Column("targeted_attempts", sa.JSON(), nullable=False),
        sa.Column("seller_profile", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "evidence_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("field_key", sa.String(length=128), nullable=False),
        sa.Column("extracted_value", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("method", sa.String(length=64), nullable=False),
        sa.Column("freshness", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_evidence_items_run_id", "evidence_items", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_evidence_items_run_id", table_name="evidence_items")
    op.drop_table("evidence_items")
    op.drop_table("research_runs")
    op.drop_table("leads")
    op.drop_index("ix_sellers_company_name", table_name="sellers")
    op.drop_table("sellers")
