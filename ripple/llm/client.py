"""LLM 客户端：Anthropic + dry-run fallback。

选择顺序（get_client 内部实现）：
  1. force_dry_run=True 参数
  2. RIPPLE_NO_LLM=1 环境变量
  3. 无 ANTHROPIC_API_KEY 且 anthropic 未安装
  → 落到 DryRunClient
"""
from __future__ import annotations

import os
from typing import Protocol

from ripple.core.config import Config
from ripple.core.logger import get_logger

log = get_logger(__name__)


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, user: str, model: str | None = None,
                 max_tokens: int = 4096) -> str: ...


class DryRunClient:
    name = "dry-run"

    def complete(self, system: str, user: str, model: str | None = None,
                 max_tokens: int = 4096) -> str:
        return "[DRY-RUN] no LLM call made.\n---\n" + user[:200]


class AnthropicClient:
    name = "anthropic"

    def __init__(self, api_key: str, default_model: str = "claude-sonnet-5"):
        try:
            import anthropic
        except ImportError as e:
            raise ImportError("需要 pip install anthropic") from e
        self._client = anthropic.Anthropic(api_key=api_key)
        self._default_model = default_model

    def complete(self, system: str, user: str, model: str | None = None,
                 max_tokens: int = 4096) -> str:
        model_id = model or self._default_model
        resp = self._client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Anthropic 返回 content: list[TextBlock]
        chunks = []
        for block in getattr(resp, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                chunks.append(text)
        return "".join(chunks)


def get_client(cfg: Config, force_dry_run: bool = False) -> LLMClient:
    if force_dry_run:
        return DryRunClient()
    if os.environ.get("RIPPLE_NO_LLM") == "1":
        log.info("RIPPLE_NO_LLM=1 → dry-run 模式")
        return DryRunClient()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("未设置 ANTHROPIC_API_KEY → dry-run 模式")
        return DryRunClient()
    try:
        return AnthropicClient(
            api_key=api_key,
            default_model=str(cfg.get("llm.briefer", "claude-sonnet-5")),
        )
    except ImportError as e:
        log.warning(f"anthropic 未安装（{e}）→ dry-run 模式")
        return DryRunClient()
