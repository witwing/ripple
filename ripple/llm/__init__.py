"""LLM 适配层：Anthropic 主实现 + dry-run 降级。"""
from ripple.llm.client import (  # noqa: F401
    AnthropicClient,
    DryRunClient,
    LLMClient,
    get_client,
)
from ripple.llm.narrator import make_narrator  # noqa: F401
