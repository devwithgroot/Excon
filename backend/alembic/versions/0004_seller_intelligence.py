"""Seller intelligence: extraction jobs, uploaded documents, normalized sources, analysis, suggestions.

Revision ID: 0004_seller_intelligence
Revises: 0003_outreach_drafts
Create Date: 2026-10-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_seller_intelligence"
down_revision: Union[str, Sequence[str], None] = "0003_outreach_drafts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "extraction_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("seller_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(length=64), nullable=False, server_default="uploading_documents"),
        sa.Column("stage_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_extraction_jobs_seller_id", "extraction_jobs", ["seller_id"])

    op.create_table(
        "source_documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("seller_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("original_format", sa.String(length=16), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("storage_path", sa.String(length=1000), nullable=True),
        sa.Column("parse_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["extraction_jobs.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_source_documents_seller_id", "source_documents", ["seller_id"])
    op.create_index("ix_source_documents_job_id", "source_documents", ["job_id"])

    op.create_table(
        "normalized_sources",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("seller_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_name", sa.String(length=500), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("original_reference", sa.String(length=1000), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("extraction_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", "job_id"),
        sa.ForeignKeyConstraint(["job_id"], ["extraction_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_normalized_sources_seller_id", "normalized_sources", ["seller_id"])

    op.create_table(
        "company_intelligence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("seller_id", sa.String(length=36), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["extraction_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_company_intelligence_seller_id", "company_intelligence", ["seller_id"])

    op.create_table(
        "profile_suggestions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("seller_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["extraction_jobs.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_profile_suggestions_seller_id", "profile_suggestions", ["seller_id"])


def downgrade() -> None:
    op.drop_index("ix_profile_suggestions_seller_id", table_name="profile_suggestions")
    op.drop_table("profile_suggestions")
    op.drop_index("ix_company_intelligence_seller_id", table_name="company_intelligence")
    op.drop_table("company_intelligence")
    op.drop_index("ix_normalized_sources_seller_id", table_name="normalized_sources")
    op.drop_table("normalized_sources")
    op.drop_index("ix_source_documents_job_id", table_name="source_documents")
    op.drop_index("ix_source_documents_seller_id", table_name="source_documents")
    op.drop_table("source_documents")
    op.drop_index("ix_extraction_jobs_seller_id", table_name="extraction_jobs")
    op.drop_table("extraction_jobs")
