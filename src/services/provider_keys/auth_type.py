"""
Provider Key 认证类型相关规则。
"""


def normalize_auth_type(raw: str) -> str:
    """将数据库中的 auth_type 归一化为逻辑类型。

    - ``"kiro"`` -> ``"oauth"``  (Kiro 使用 OAuth 流程)
    - ``"vertex_ai"`` -> ``"service_account"``  (旧的 Vertex AI auth_type 已重命名)
    """
    t = str(raw or "api_key").strip() or "api_key"
    if t == "kiro":  # TODO: 迁移稳定后清理，同步清理各处 in ("...", "kiro") 兼容检查
        return "oauth"
    if t == "vertex_ai":  # TODO: 迁移稳定后清理，同步清理各处 in ("...", "vertex_ai") 兼容检查
        return "service_account"
    return t
