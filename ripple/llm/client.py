"""LLM 客户端：Anthropic HTTP + dry-run fallback。

**为什么直接用 httpx 而不是 anthropic SDK**：
- 需要支持内部网关（如 `cisai.byteintl.net`）的 `x-api-key` + `anthropic-version` 契约
- 需要在只有 IPv6 可达的网络里强制走 v6（httpx.HTTPTransport(local_address="::"）
- SDK 层的 timeout / retry 语义我们自己实现

选择顺序（get_client 内部实现）：
  1. force_dry_run=True 参数
  2. RIPPLE_NO_LLM=1 环境变量
  3. 没有 API key（env `ANTHROPIC_AUTH_TOKEN` 或 `ANTHROPIC_API_KEY`）
  → 落到 DryRunClient
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from ripple.core.config import Config
from ripple.core.logger import get_logger

log = get_logger(__name__)

ANTHROPIC_VERSION = "2023-06-01"


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, user: str, model: str | None = None,
                 max_tokens: int = 4096) -> str: ...


class DryRunClient:
    name = "dry-run"

    def complete(self, system: str, user: str, model: str | None = None,
                 max_tokens: int = 4096) -> str:
        return "[DRY-RUN] no LLM call made.\n---\n" + user[:200]


@dataclass
class AnthropicHTTPSettings:
    base_url: str
    api_key: str
    default_model: str
    timeout: int = 300
    force_ipv6: bool = False
    temperature: float = 0.0


class AnthropicHTTPClient:
    """直接调 Anthropic /v1/messages 兼容端点（含内部网关）。"""

    name = "anthropic-http"

    def __init__(self, settings: AnthropicHTTPSettings):
        try:
            import httpx
        except ImportError as e:
            raise ImportError("需要 pip install httpx") from e
        self._httpx = httpx
        self._settings = settings
        transport = (
            httpx.HTTPTransport(local_address="::") if settings.force_ipv6 else None
        )
        self._client = httpx.Client(transport=transport, timeout=settings.timeout)

    def complete(self, system: str, user: str, model: str | None = None,
                 max_tokens: int = 4096) -> str:
        url = f"{self._settings.base_url.rstrip('/')}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if self._settings.api_key:
            headers["x-api-key"] = self._settings.api_key
        payload: dict = {
            "model": model or self._settings.default_model,
            "messages": [{"role": "user", "content": user}],
            "temperature": self._settings.temperature,
            "max_tokens": max_tokens,
        }
        if system:
            payload["system"] = system

        try:
            resp = self._client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except self._httpx.HTTPStatusError as e:
            body = e.response.text[:500] if e.response is not None else ""
            raise RuntimeError(f"LLM 返回 {e.response.status_code}: {body}") from e
        except self._httpx.HTTPError as e:
            raise RuntimeError(f"LLM 请求失败：{e}") from e
        except ValueError as e:
            raise RuntimeError(f"LLM 响应非 JSON：{e}") from e

        try:
            return "".join(
                b.get("text", "") for b in data["content"] if b.get("type") == "text"
            )
        except (KeyError, TypeError) as e:
            raise RuntimeError(f"LLM 响应结构异常：{data}") from e

    def close(self) -> None:
        self._client.close()


# 保留兼容名，指向新实现
AnthropicClient = AnthropicHTTPClient


def get_client(cfg: Config, force_dry_run: bool = False) -> LLMClient:
    if force_dry_run:
        return DryRunClient()
    if os.environ.get("RIPPLE_NO_LLM") == "1":
        log.info("RIPPLE_NO_LLM=1 → dry-run 模式")
        return DryRunClient()

    # 优先内部网关的 token；然后 Anthropic 官方 key
    api_key = (
        os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("ANTHROPIC_API_KEY")
        or ""
    )
    if not api_key:
        log.warning("未设置 ANTHROPIC_AUTH_TOKEN / ANTHROPIC_API_KEY → dry-run 模式")
        return DryRunClient()

    base_url = (
        os.environ.get("ANTHROPIC_BASE_URL")
        or str(cfg.get("llm.base_url", "https://api.anthropic.com"))
    )
    # 环境变量覆盖 config 的 model；便于同一份 config 在不同环境用不同模型
    default_model = (
        os.environ.get("ANTHROPIC_MODEL")
        or str(cfg.get("llm.briefer", "claude-sonnet-5"))
    )
    force_ipv6 = str(cfg.get("llm.force_ipv6", "false")).lower() in ("1", "true", "yes")
    if os.environ.get("RIPPLE_FORCE_IPV6") == "1":
        force_ipv6 = True
    # 内部网关默认强制走 IPv6（IPv4 不通已知问题）
    if "byteintl.net" in base_url or "bytedance" in base_url:
        force_ipv6 = True

    try:
        settings = AnthropicHTTPSettings(
            base_url=base_url,
            api_key=api_key,
            default_model=default_model,
            force_ipv6=force_ipv6,
        )
        return AnthropicHTTPClient(settings)
    except ImportError as e:
        log.warning(f"httpx 未安装（{e}）→ dry-run 模式")
        return DryRunClient()
