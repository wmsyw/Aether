"""
Provider Key 认证类型相关规则。
"""


def normalize_auth_type(raw: str) -> str:
    """将数据库中的 auth_type 归一化为逻辑类型。

    Kiro 在数据库中存储为 ``"kiro"`` 或 ``"oauth"``，统一映射为 ``"oauth"``。
    """
    t = str(raw or "api_key").strip() or "api_key"
    return "oauth" if t == "kiro" else t
