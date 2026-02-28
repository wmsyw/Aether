"""proxy_node_metrics_and_events

Revision ID: 48afe197cc15
Revises: b2c3d4e5f6a7
Create Date: 2026-02-28 04:33:11.201185+00:00

"""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision = "48afe197cc15"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    columns = [c["name"] for c in insp.get_columns(table_name)]
    return column_name in columns


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return table_name in insp.get_table_names()


def upgrade() -> None:
    # proxy_nodes: 新增错误指标字段
    if not _column_exists("proxy_nodes", "failed_requests"):
        op.add_column(
            "proxy_nodes",
            sa.Column(
                "failed_requests",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
                comment="累计失败请求数",
            ),
        )
    if not _column_exists("proxy_nodes", "dns_failures"):
        op.add_column(
            "proxy_nodes",
            sa.Column(
                "dns_failures",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
                comment="累计 DNS 失败数",
            ),
        )
    if not _column_exists("proxy_nodes", "stream_errors"):
        op.add_column(
            "proxy_nodes",
            sa.Column(
                "stream_errors",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
                comment="累计流错误数",
            ),
        )

    # proxy_node_events: 连接事件表
    if not _table_exists("proxy_node_events"):
        op.create_table(
            "proxy_node_events",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("node_id", sa.String(length=36), nullable=False),
            sa.Column(
                "event_type",
                sa.String(length=20),
                nullable=False,
                comment="事件类型: connected, disconnected, error",
            ),
            sa.Column(
                "detail",
                sa.String(length=500),
                nullable=True,
                comment="事件详情（如断开原因）",
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["node_id"], ["proxy_nodes.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "idx_proxy_node_events_node_created",
            "proxy_node_events",
            ["node_id", "created_at"],
        )
        op.create_index(
            op.f("ix_proxy_node_events_node_id"),
            "proxy_node_events",
            ["node_id"],
        )


def downgrade() -> None:
    if _table_exists("proxy_node_events"):
        op.drop_index(op.f("ix_proxy_node_events_node_id"), table_name="proxy_node_events")
        op.drop_index("idx_proxy_node_events_node_created", table_name="proxy_node_events")
        op.drop_table("proxy_node_events")
    if _column_exists("proxy_nodes", "stream_errors"):
        op.drop_column("proxy_nodes", "stream_errors")
    if _column_exists("proxy_nodes", "dns_failures"):
        op.drop_column("proxy_nodes", "dns_failures")
    if _column_exists("proxy_nodes", "failed_requests"):
        op.drop_column("proxy_nodes", "failed_requests")
