"""Advisor：从简报 markdown 里抽取 §五 结论的 JSON 段。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


VALID_ACTIONS = {"buy", "sell", "hold", "watch"}


@dataclass
class ParsedAdvice:
    action: str
    size_pct: float
    confidence: float
    horizon_days: int
    rationale: str


_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def parse_from_brief(markdown: str) -> ParsedAdvice:
    """解析 brief markdown 末尾的 ```json``` 结论块；失败时返回保守默认。

    取**最后一个** JSON 代码块，避免 LLM 在正文中嵌入示例 JSON 时误配。
    """
    matches = _JSON_BLOCK.findall(markdown)
    if not matches:
        return _fallback("未找到 JSON 结论块")
    try:
        data = json.loads(matches[-1])
    except json.JSONDecodeError as e:
        return _fallback(f"JSON 解析失败：{e}")

    action = str(data.get("action", "watch")).lower()
    if action not in VALID_ACTIONS:
        action = "watch"

    return ParsedAdvice(
        action=action,
        size_pct=_clamp(_to_float(data.get("size_pct")), 0, 100, default=0.0),
        confidence=_clamp(_to_float(data.get("confidence")), 0, 1, default=0.0),
        horizon_days=int(_to_float(data.get("horizon_days")) or 30),
        rationale=str(data.get("rationale", ""))[:512],
    )


def _fallback(reason: str) -> ParsedAdvice:
    return ParsedAdvice(
        action="watch", size_pct=0.0, confidence=0.0, horizon_days=30, rationale=reason
    )


def _to_float(x) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _clamp(v: float | None, lo: float, hi: float, default: float) -> float:
    if v is None:
        return default
    return max(lo, min(hi, v))
