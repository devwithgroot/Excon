"""Outreach drafts and version history.

Revision ID: 0003_outreach_drafts
Revises: 0002_seller_versions_reports
Create Date: 2026-10-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_outreach_drafts"
down_revision: Union[str, Sequence[str], None] = "0002_seller_versions_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outreach_drafts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("seller_id", sa.String(length=36), nullable=True),
        sa.Column("person_evidence_id", sa.String(length=36), nullable=False),
        sa.Column("person_name", sa.String(length=255), nullable=False),
        sa.Column("person_title", sa.String(length=255), nullable=True),
        sa.Column("person_linkedin_url", sa.String(length=1000), nullable=True),
        sa.Column("offering", sa.Text(), nullable=True),
        sa.Column("offering_reason", sa.Text(), nullable=True),
        sa.Column("relevance", sa.Text(), nullable=False),
        sa.Column("cited_facts", sa.JSON(), nullable=False),
        sa.Column("linkedin_connect", sa.Text(), nullable=False),
        sa.Column("linkedin_message", sa.Text(), nullable=False),
        sa.Column("whatsapp", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("run_id", "person_evidence_id", name="uq_outreach_drafts_run_person"),
    )
    op.create_index("ix_outreach_drafts_run_id", "outreach_drafts", ["run_id"])
    op.create_table(
        "outreach_draft_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["outreach_drafts.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_outreach_draft_versions_draft_id", "outreach_draft_versions", ["draft_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_outreach_draft_versions_draft_id", table_name="outreach_draft_versions")
    op.drop_table("outreach_draft_versions")
    op.drop_index("ix_outreach_drafts_run_id", table_name="outreach_drafts")
    op.drop_table("outreach_drafts")
