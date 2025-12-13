"""
数据库方言兼容性辅助函数
"""

from typing import Any

from sqlalchemy import func


def date_trunc_portable(dialect_name: str, interval: str, column: Any) -> Any:
    """
    跨数据库的日期截断函数

    Args:
        dialect_name: 数据库方言名称 ('postgresql', 'sqlite', 'mysql')
        interval: 时间间隔 ('day', 'week', 'month', 'year')
        column: 日期列

    Returns:
        SQLAlchemy ClauseElement

    Raises:
        NotImplementedError: 不支持的数据库方言

    Examples:
        >>> # PostgreSQL
        >>> period_func = date_trunc_portable('postgresql', 'week', Usage.created_at)
        >>> # 等价于: func.date_trunc('week', Usage.created_at)

        >>> # SQLite
        >>> period_func = date_trunc_portable('sqlite', 'month', Usage.created_at)
        >>> # 等价于: func.strftime("%Y-%m", Usage.created_at)
    """
    if dialect_name == "postgresql":
        # PostgreSQL 使用 date_trunc 函数
        return func.date_trunc(interval, column)

    elif dialect_name == "sqlite":
        # SQLite 使用 strftime 函数
        format_map = {
            "year": "%Y",
            "month": "%Y-%m",
            "week": "%Y-%W",
            "day": "%Y-%m-%d",
        }
        if interval not in format_map:
            raise ValueError(f"Unsupported interval for SQLite: {interval}")
        return func.strftime(format_map[interval], column)

    elif dialect_name == "mysql":
        # MySQL 使用 date_format 函数
        format_map = {
            "year": "%Y",
            "month": "%Y-%m",
            "day": "%Y-%m-%d",
        }
        if interval not in format_map:
            raise ValueError(f"Unsupported interval for MySQL: {interval}")
        return func.date_format(column, format_map[interval])

    else:
        raise NotImplementedError(
            f"Unsupported database dialect: {dialect_name}. "
            f"Supported dialects: postgresql, sqlite, mysql"
        )
