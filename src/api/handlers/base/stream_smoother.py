"""
流式平滑输出处理器

将上游返回的大 chunk 拆分成小块，模拟更流畅的打字效果。
支持 OpenAI、Claude、Gemini 格式的 SSE 事件。
"""

import asyncio
import copy
import json
from typing import AsyncGenerator, Optional, Tuple


class StreamSmoother:
    """
    流式平滑输出处理器

    将 SSE 事件中的大段 content 拆分成小块输出，
    每块之间加入微小延迟，模拟打字效果。
    """

    def __init__(
        self,
        chunk_size: int = 5,
        delay_ms: int = 15,
    ):
        """
        初始化平滑处理器

        Args:
            chunk_size: 每个小块的字符数
            delay_ms: 每个小块之间的延迟毫秒数
        """
        self.chunk_size = chunk_size
        self.delay_ms = delay_ms
        self.delay_seconds = self.delay_ms / 1000.0

    def _split_content(self, content: str) -> list[str]:
        """
        将内容按字符数拆分

        对于中文等多字节字符，按字符（而非字节）拆分。
        """
        if len(content) <= self.chunk_size:
            return [content]

        chunks = []
        for i in range(0, len(content), self.chunk_size):
            chunks.append(content[i : i + self.chunk_size])
        return chunks

    def _extract_content(self, data: dict) -> Tuple[Optional[str], str]:
        """
        从 SSE 数据中提取可拆分的 content

        Returns:
            (content, format): content 为提取的文本，format 为检测到的格式
            format: "openai" | "claude" | "gemini" | "unknown"
        """
        if not isinstance(data, dict):
            return None, "unknown"

        # OpenAI 格式: choices[0].delta.content
        # 只在 delta 仅包含 role/content 时允许拆分，避免破坏 tool_calls 等结构
        choices = data.get("choices")
        if isinstance(choices, list) and len(choices) == 1:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                delta = first_choice.get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if isinstance(content, str):
                        allowed_keys = {"role", "content"}
                        if all(key in allowed_keys for key in delta.keys()):
                            return content, "openai"

        # Claude 格式: type=content_block_delta, delta.type=text_delta, delta.text
        if data.get("type") == "content_block_delta":
            delta = data.get("delta", {})
            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                text = delta.get("text")
                if isinstance(text, str):
                    return text, "claude"

        # Gemini 格式: candidates[0].content.parts[0].text
        candidates = data.get("candidates")
        if isinstance(candidates, list) and len(candidates) == 1:
            first_candidate = candidates[0]
            if isinstance(first_candidate, dict):
                content = first_candidate.get("content", {})
                if isinstance(content, dict):
                    parts = content.get("parts", [])
                    if isinstance(parts, list) and len(parts) == 1:
                        first_part = parts[0]
                        if isinstance(first_part, dict):
                            text = first_part.get("text")
                            # 只有纯文本块才拆分
                            if isinstance(text, str) and len(first_part) == 1:
                                return text, "gemini"

        return None, "unknown"

    def _create_openai_chunk(
        self,
        original_data: dict,
        new_content: str,
        is_first: bool = False,
    ) -> bytes:
        """创建 OpenAI 格式的 SSE chunk"""
        new_data = original_data.copy()

        if "choices" in new_data and new_data["choices"]:
            new_choices = []
            for choice in new_data["choices"]:
                new_choice = choice.copy()
                if "delta" in new_choice:
                    new_delta = {}
                    # 只有第一个 chunk 保留 role
                    if is_first and "role" in new_choice["delta"]:
                        new_delta["role"] = new_choice["delta"]["role"]
                    new_delta["content"] = new_content
                    new_choice["delta"] = new_delta
                new_choices.append(new_choice)
            new_data["choices"] = new_choices

        return f"data: {json.dumps(new_data, ensure_ascii=False)}\n\n".encode("utf-8")

    def _create_claude_chunk(
        self,
        original_data: dict,
        new_content: str,
        event_type: str,
    ) -> bytes:
        """创建 Claude 格式的 SSE chunk"""
        new_data = original_data.copy()

        if "delta" in new_data:
            new_delta = new_data["delta"].copy()
            new_delta["text"] = new_content
            new_data["delta"] = new_delta

        # Claude 格式需要 event: 前缀
        return f"event: {event_type}\ndata: {json.dumps(new_data, ensure_ascii=False)}\n\n".encode(
            "utf-8"
        )

    def _create_gemini_chunk(
        self,
        original_data: dict,
        new_content: str,
    ) -> bytes:
        """创建 Gemini 格式的 SSE chunk"""
        new_data = copy.deepcopy(original_data)

        if "candidates" in new_data and new_data["candidates"]:
            first_candidate = new_data["candidates"][0]
            if "content" in first_candidate:
                content = first_candidate["content"]
                if "parts" in content and content["parts"]:
                    content["parts"][0]["text"] = new_content

        return f"data: {json.dumps(new_data, ensure_ascii=False)}\n\n".encode("utf-8")

    async def smooth_stream(
        self,
        byte_iterator: AsyncGenerator[bytes, None],
    ) -> AsyncGenerator[bytes, None]:
        """
        对字节流进行平滑处理

        解析 SSE 事件，拆分大 content，添加延迟后输出。

        Args:
            byte_iterator: 原始字节流

        Yields:
            平滑处理后的字节块
        """
        buffer = b""
        is_first_content = True

        async for chunk in byte_iterator:
            buffer += chunk

            # 按双换行分割 SSE 事件（标准 SSE 格式）
            while b"\n\n" in buffer:
                event_block, buffer = buffer.split(b"\n\n", 1)
                event_str = event_block.decode("utf-8", errors="replace")

                # 解析事件块
                lines = event_str.strip().split("\n")
                data_str = None
                event_type = ""

                for line in lines:
                    line = line.rstrip("\r")
                    if line.startswith("event: "):
                        event_type = line[7:].strip()
                    elif line.startswith("data: "):
                        data_str = line[6:]

                # 没有 data 行，直接透传
                if data_str is None:
                    yield event_block + b"\n\n"
                    continue

                # [DONE] 直接透传
                if data_str.strip() == "[DONE]":
                    yield event_block + b"\n\n"
                    continue

                # 尝试解析 JSON
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    yield event_block + b"\n\n"
                    continue

                # 提取 content 和格式
                content, fmt = self._extract_content(data)

                if content and len(content) > self.chunk_size:
                    # 需要拆分
                    content_chunks = self._split_content(content)

                    for i, sub_content in enumerate(content_chunks):
                        is_first = is_first_content and i == 0

                        if fmt == "openai":
                            sse_chunk = self._create_openai_chunk(data, sub_content, is_first)
                        elif fmt == "claude":
                            sse_chunk = self._create_claude_chunk(
                                data, sub_content, event_type or "content_block_delta"
                            )
                        elif fmt == "gemini":
                            sse_chunk = self._create_gemini_chunk(data, sub_content)
                        else:
                            # 未知格式，透传原始事件
                            yield event_block + b"\n\n"
                            break

                        yield sse_chunk

                        # 除了最后一个块，其他块之间加延迟
                        if i < len(content_chunks) - 1:
                            await asyncio.sleep(self.delay_seconds)
                    else:
                        is_first_content = False
                else:
                    # 不需要拆分，直接透传
                    yield event_block + b"\n\n"
                    if content:
                        is_first_content = False

        # 处理剩余数据
        if buffer:
            yield buffer
