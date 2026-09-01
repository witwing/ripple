"""从完整简报里抽取"判断"部分，做成可与图表配对的精简文字。

设计理念：图表承载**事实**（数字/信号/走势），文字只承载**判断**——
为什么这些事实凑在一起重要、什么会改变它、该怎么做。
所以 digest 只取：一句话定性 + 短/中/长期洞察 + 投资价值分析 + 结论动作。
不重复图里已有的 PE/ROE/公告清单。
"""
from __future__ import annotations

import re

from ripple.analyze.advisor import ParsedAdvice

# 想保留的判断类章节标题关键词
_KEEP_HEADS = ("短", "中", "长", "投资价值分析", "洞察")


def _extract_sections(markdown: str, keywords: tuple[str, ...]) -> list[str]:
    """按 '## ' 切段，保留标题命中任一关键词的段落（去掉纯数据段）。"""
    blocks = re.split(r"\n(?=## )", markdown)
    out = []
    for b in blocks:
        head = b.splitlines()[0] if b.strip() else ""
        if head.startswith("## ") and any(k in head for k in keywords):
            out.append(b.strip())
    return out


def build_digest(markdown: str, advice: ParsedAdvice, name: str, code: str) -> str:
    """生成配图文字：动作条 + 周期观点 + 判断章节。"""
    L: list[str] = []

    # 动作条
    action_cn = {"buy": "买入", "sell": "卖出", "hold": "持有", "watch": "观望"}.get(
        advice.action, advice.action
    )
    L.append(f"**{name}（{code}）· {action_cn}**  "
             f"仓位 {advice.size_pct:.0f}%  ·  置信度 {advice.confidence:.0%}")

    # 周期观点一行
    if advice.horizon_views:
        hv = advice.horizon_views
        L.append(f"短期 {hv.get('short','-')}  ·  中期 {hv.get('mid','-')}  ·  长期 {hv.get('long','-')}")

    # 一句话结论
    if advice.rationale:
        L.append(f"\n> {advice.rationale}")

    # 判断章节（短中长期 + 价值分析）
    sections = _extract_sections(markdown, _KEEP_HEADS)
    if sections:
        L.append("")
        L.append("\n\n".join(sections))

    return "\n".join(L)
