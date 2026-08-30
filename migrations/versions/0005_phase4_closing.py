"""Phase 4 immutable business-day closing records."""
from alembic import op
import sqlalchemy as sa

revision = "0005_phase4_closing"
down_revision = "0004_phase3_cash_control"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("closing_records", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("business_day_id", sa.Integer(), sa.ForeignKey("business_days.id", ondelete="RESTRICT"), nullable=False, unique=True), sa.Column("cash_count_id", sa.Integer(), sa.ForeignKey("cash_counts.id", ondelete="RESTRICT"), nullable=False), sa.Column("expected_khr_minor", sa.BigInteger(), nullable=False), sa.Column("actual_khr_minor", sa.BigInteger(), nullable=False), sa.Column("difference_khr_minor", sa.BigInteger(), nullable=False), sa.Column("expected_usd_minor", sa.BigInteger(), nullable=False), sa.Column("actual_usd_minor", sa.BigInteger(), nullable=False), sa.Column("difference_usd_minor", sa.BigInteger(), nullable=False), sa.Column("aba_khr_minor", sa.BigInteger(), nullable=False), sa.Column("aba_usd_minor", sa.BigInteger(), nullable=False), sa.Column("expense_count", sa.Integer(), nullable=False), sa.Column("cash_movement_count", sa.Integer(), nullable=False), sa.Column("explanation_khr", sa.Text()), sa.Column("explanation_usd", sa.Text()), sa.Column("aba_confirmed", sa.Boolean(), nullable=False), sa.Column("closed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True))
    op.create_table("business_day_reopenings", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("business_day_id", sa.Integer(), sa.ForeignKey("business_days.id", ondelete="RESTRICT"), nullable=False), sa.Column("reason", sa.Text(), nullable=False), sa.Column("reopened_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=False), sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True))

def downgrade() -> None:
    op.drop_table("business_day_reopenings")
    op.drop_table("closing_records")
