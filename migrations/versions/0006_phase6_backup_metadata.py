"""Phase 6 verified backup metadata."""
from alembic import op
import sqlalchemy as sa
revision="0006_phase6_backup_metadata"
down_revision="0005_phase4_closing"
branch_labels=None
depends_on=None
def upgrade():
    op.create_table("backup_metadata",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("relative_path",sa.String(500),nullable=False,unique=True),sa.Column("size_bytes",sa.BigInteger(),nullable=False),sa.Column("sha256",sa.String(64),nullable=False),sa.Column("integrity_ok",sa.Boolean(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("created_by_user_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="RESTRICT")))
def downgrade(): op.drop_table("backup_metadata")
