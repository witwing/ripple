"""Ripple 配置：读 config.yaml，缺失就写默认值。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

from ripple.core import paths


DEFAULT_CONFIG: dict[str, Any] = {
    "providers": {
        "quote": ["akshare"],
        "fundamental": ["akshare"],
        "disclosure": ["akshare"],
        "news": ["akshare"],
        "meta": ["akshare"],
    },
    "strategy": "fallback",
    "cache": {
        "enabled": True,
        "ttl_hours": {
            "daily_kline": 12,
            "snapshot": 0.1,
            "financial_reports": 240,
            "valuation": 12,
            "profile": 240,
            "announcements": 6,
            "news": 1,
        },
    },
    "rate_limit": {
        "akshare": 5,
    },
    "embed": {
        "model": "BAAI/bge-small-zh-v1.5",
        "chunk_token_threshold": 400,
    },
    "llm": {
        "briefer": "claude-sonnet-5",
        "tagger": "claude-haiku-4-5-20251001",
    },
}


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=dict)

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def providers_for(self, capability: str) -> list[str]:
        return list(self.get(f"providers.{capability}", []))

    @property
    def strategy(self) -> str:
        return str(self.get("strategy", "fallback"))


def load() -> Config:
    """加载配置；文件不存在则用默认值写一份出来，方便用户改。"""
    paths.ensure_layout()
    cfg_path = paths.config_path()
    if not cfg_path.exists():
        cfg_path.write_text(
            yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    # 合并默认值以宽容用户删掉的键
    merged = _deep_merge(DEFAULT_CONFIG, data)
    return Config(raw=merged)


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
