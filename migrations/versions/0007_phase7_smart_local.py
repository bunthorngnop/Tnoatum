"""Phase 7 deterministic local convenience records."""
from alembic import op
import sqlalchemy as sa
revision="0007_phase7_smart_local"; down_revision="0006_phase6_backup_metadata"; branch_labels=None; depends_on=None
def upgrade():
    op.create_table("product_aliases",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("product_id",sa.Integer(),sa.ForeignKey("products.id",ondelete="RESTRICT"),nullable=False),sa.Column("alias",sa.String(160),nullable=False,unique=True),sa.Column("is_active",sa.Boolean(),nullable=False,server_default=sa.true()),sa.Column("created_by_user_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("product_favorites",sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="RESTRICT"),primary_key=True),sa.Column("product_id",sa.Integer(),sa.ForeignKey("products.id",ondelete="RESTRICT"),primary_key=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("smart_suggestions",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("suggestion_type",sa.String(40),nullable=False),sa.Column("key",sa.String(200),nullable=False,unique=True),sa.Column("payload_json",sa.JSON(),nullable=False),sa.Column("status",sa.String(16),nullable=False,server_default="PENDING"),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("decided_at",sa.DateTime(timezone=True)),sa.Column("decided_by_user_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="RESTRICT")),sa.CheckConstraint("status IN ('PENDING','ACCEPTED','IGNORED')",name="ck_smart_suggestion_status"))
def downgrade(): op.drop_table("smart_suggestions"); op.drop_table("product_favorites"); op.drop_table("product_aliases")
