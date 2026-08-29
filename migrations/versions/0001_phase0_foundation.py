"""Phase 0 identity, permissions, business day, audit, settings, idempotency."""
from alembic import op
import sqlalchemy as sa

revision = "0001_phase0_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("permissions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(80), nullable=False, unique=True), sa.Column("description", sa.Text(), nullable=False))
    op.create_table("roles", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(32), nullable=False, unique=True), sa.Column("name", sa.String(80), nullable=False), sa.Column("description", sa.Text()), sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table("users", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("telegram_user_id", sa.BigInteger(), nullable=False, unique=True), sa.Column("display_name", sa.String(120), nullable=False), sa.Column("telegram_username", sa.String(64)), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.CheckConstraint("telegram_user_id > 0", name="ck_users_telegram_id_positive"))
    op.create_table("role_permissions", sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True), sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id", ondelete="RESTRICT"), primary_key=True))
    op.create_table("user_roles", sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True), sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True))
    op.create_table("user_permission_overrides", sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True), sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id", ondelete="RESTRICT"), primary_key=True), sa.Column("allowed", sa.Boolean(), nullable=False), sa.Column("reason", sa.Text(), nullable=False), sa.Column("granted_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("business_days", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("business_date", sa.Date(), nullable=False, unique=True), sa.Column("status", sa.String(24), nullable=False, server_default="OPEN"), sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False), sa.Column("opened_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("closing_started_at", sa.DateTime(timezone=True)), sa.Column("closing_started_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT")), sa.Column("closed_at", sa.DateTime(timezone=True)), sa.Column("closed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT")), sa.CheckConstraint("status IN ('OPEN','CLOSING_PENDING','CLOSED')", name="ck_business_day_status"))
    op.create_index("uq_one_active_business_day", "business_days", [sa.text("1")], unique=True, sqlite_where=sa.text("status != 'CLOSED'"))
    op.create_table("audit_logs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False), sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT")), sa.Column("actor_telegram_user_id", sa.BigInteger()), sa.Column("action", sa.String(80), nullable=False), sa.Column("entity_type", sa.String(80), nullable=False), sa.Column("entity_id", sa.String(80)), sa.Column("old_values", sa.JSON()), sa.Column("new_values", sa.JSON()), sa.Column("reason", sa.Text()), sa.Column("approver_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT")), sa.Column("correlation_id", sa.String(100), nullable=False))
    op.create_index("ix_audit_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_table("app_settings", sa.Column("key", sa.String(100), primary_key=True), sa.Column("value_json", sa.JSON(), nullable=False), sa.Column("is_sensitive", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT")))
    op.create_table("idempotency_records", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("namespace", sa.String(80), nullable=False), sa.Column("request_key", sa.String(160), nullable=False), sa.Column("response_json", sa.JSON()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("namespace", "request_key", name="uq_idempotency_namespace_key"))


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_table("app_settings")
    op.drop_index("ix_audit_entity", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("uq_one_active_business_day", table_name="business_days")
    op.drop_table("business_days")
    op.drop_table("user_permission_overrides")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("permissions")
