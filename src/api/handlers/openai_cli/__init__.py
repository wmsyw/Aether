"""
OpenAI CLI 透传处理器
"""

from src.api.handlers.openai_cli.adapter import OpenAICliAdapter, OpenAICompactAdapter
from src.api.handlers.openai_cli.handler import OpenAICliMessageHandler

__all__ = [
    "OpenAICliAdapter",
    "OpenAICompactAdapter",
    "OpenAICliMessageHandler",
]
