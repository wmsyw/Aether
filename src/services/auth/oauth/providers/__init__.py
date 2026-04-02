"""内置 OAuth providers（v1）。"""

from .github import GitHubOAuthProvider
from .linuxdo import LinuxDoOAuthProvider

__all__ = ["GitHubOAuthProvider", "LinuxDoOAuthProvider"]
