"""add passkey credentials table for webauthn authentication

Revision ID: 20260331_1500_add_passkey_credentials
Revises: 20260324_1400_c3d4e5f6a7b8
Create Date: 2026-03-31 15:00:00.000000+00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260331_1500_add_passkey_credentials"
down_revision = "20260324_1400_c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建 user_passkey_credentials 表"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_passkey_credentials" in inspector.get_table_names():
        return

    op.create_table(
        "user_passkey_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("credential_id", sa.String(length=512), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("device_name", sa.String(length=100), nullable=True),
        sa.Column("device_type", sa.String(length=50), nullable=True),
        sa.Column("backed_up", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("transports", sa.JSON(), nullable=True),
        sa.Column("aaguid", sa.String(length=36), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credential_id"),
    )

    # 创建索引
    op.create_index(
        "idx_passkey_credentials_user_id",
        "user_passkey_credentials",
        ["user_id"],
    )
    op.create_index(
        "idx_passkey_credentials_user_active",
        "user_passkey_credentials",
        ["user_id", "is_active"],
    )
    op.create_index(
        "idx_passkey_credentials_credential_id",
        "user_passkey_credentials",
        ["credential_id"],
    )


def downgrade() -> None:
    """删除 user_passkey_credentials 表"""
    op.drop_index(
        "idx_passkey_credentials_credential_id", table_name="user_passkey_credentials"
    )
    op.drop_index(
        "idx_passkey_credentials_user_active", table_name="user_passkey_credentials"
    )
    op.drop_index(
        "idx_passkey_credentials_user_id", table_name="user_passkey_credentials"
    )
    op.drop_table("user_passkey_credentials")
