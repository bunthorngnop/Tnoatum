"""Phase 3 physical cash control, retained floats, and cash counts."""
from alembic import op
import sqlalchemy as sa

revision = "0004_phase3_cash_control"
down_revision = "0003_phase2_expenses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("cash_movements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_day_id", sa.Integer(), sa.ForeignKey("business_days.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("movement_type", sa.String(24), nullable=False), sa.Column("direction", sa.String(12), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False), sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False), sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("related_entity_type", sa.String(40)), sa.Column("related_entity_id", sa.String(80)),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("reversed_movement_id", sa.Integer(), sa.ForeignKey("cash_movements.id", ondelete="RESTRICT"), unique=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True), sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("movement_type IN ('OPENING_FLOAT','DEPOSIT','WITHDRAWAL','OWNER_WITHDRAWAL','ADJUSTMENT','REVERSAL')", name="ck_cash_movement_type"),
        sa.CheckConstraint("direction IN ('INFLOW','OUTFLOW')", name="ck_cash_movement_direction"),
        sa.CheckConstraint("amount_minor > 0", name="ck_cash_movement_amount"), sa.CheckConstraint("currency IN ('KHR','USD')", name="ck_cash_movement_currency"))
    op.create_index("ix_cash_movement_day_currency", "cash_movements", ["business_day_id", "currency"])
    op.create_index("uq_cash_opening_currency_day", "cash_movements", ["business_day_id", "currency"], unique=True, sqlite_where=sa.text("movement_type = 'OPENING_FLOAT'"))
    op.create_table("retained_floats",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("business_day_id", sa.Integer(), sa.ForeignKey("business_days.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False), sa.Column("amount_minor", sa.BigInteger(), nullable=False), sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True), sa.CheckConstraint("currency IN ('KHR','USD')", name="ck_retained_float_currency"),
        sa.CheckConstraint("amount_minor >= 0", name="ck_retained_float_amount"))
    op.create_table("cash_counts",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("business_day_id", sa.Integer(), sa.ForeignKey("business_days.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actual_khr_minor", sa.BigInteger(), nullable=False), sa.Column("actual_usd_minor", sa.BigInteger(), nullable=False),
        sa.Column("expected_khr_minor", sa.BigInteger(), nullable=False), sa.Column("expected_usd_minor", sa.BigInteger(), nullable=False),
        sa.Column("difference_khr_minor", sa.BigInteger(), nullable=False), sa.Column("difference_usd_minor", sa.BigInteger(), nullable=False),
        sa.Column("counted_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("counted_at", sa.DateTime(timezone=True), nullable=False), sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        sa.CheckConstraint("actual_khr_minor >= 0 AND actual_usd_minor >= 0", name="ck_cash_count_actual_nonnegative"))


def downgrade() -> None:
    op.drop_table("cash_counts")
    op.drop_table("retained_floats")
    op.drop_index("uq_cash_opening_currency_day", table_name="cash_movements")
    op.drop_index("ix_cash_movement_day_currency", table_name="cash_movements")
    op.drop_table("cash_movements")
