"""add usage table composite indexes for query optimization

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2025-12-20 15:00:00.000000+00:00

"""
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6g7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def index_exists(table_name: str, index_name: str) -> bool:
    """检查索引是否存在"""
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade() -> None:
    """为 usage 表添加复合索引以优化常见查询"""
    # 1. user_id + created_at 复合索引 (用户用量查询)
    if not index_exists('usage', 'idx_usage_user_created'):
        op.create_index(
            'idx_usage_user_created',
            'usage',
            ['user_id', 'created_at'],
            postgresql_concurrently=True
        )

    # 2. api_key_id + created_at 复合索引 (API Key 用量查询)
    if not index_exists('usage', 'idx_usage_apikey_created'):
        op.create_index(
            'idx_usage_apikey_created',
            'usage',
            ['api_key_id', 'created_at'],
            postgresql_concurrently=True
        )

    # 3. provider + model + created_at 复合索引 (模型统计查询)
    if not index_exists('usage', 'idx_usage_provider_model_created'):
        op.create_index(
            'idx_usage_provider_model_created',
            'usage',
            ['provider', 'model', 'created_at'],
            postgresql_concurrently=True
        )


def downgrade() -> None:
    """删除复合索引"""
    if index_exists('usage', 'idx_usage_provider_model_created'):
        op.drop_index('idx_usage_provider_model_created', table_name='usage')

    if index_exists('usage', 'idx_usage_apikey_created'):
        op.drop_index('idx_usage_apikey_created', table_name='usage')

    if index_exists('usage', 'idx_usage_user_created'):
        op.drop_index('idx_usage_user_created', table_name='usage')
