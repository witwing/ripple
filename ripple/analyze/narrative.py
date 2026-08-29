"""Narrative：装配 LLM 上下文 + dry-run 时的模板渲染。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ripple.analyze.profile import Profile
from ripple.notes.search import Hit
from ripple.providers.base import Announcement, NewsItem


@dataclass
class BriefContext:
    ticker: dict
    profile: dict
    recent_kline_summary: str
    announcements: list[dict] = field(default_factory=list)
    news: list[dict] = field(default_factory=list)
    recalled_notes: list[dict] = field(default_factory=list)
    user_stance: str = ""


def _summarize_kline(profile: Profile) -> str:
    parts = []
    if profile.kline_range_pct_20d is not None:
        parts.append(f"近 20 日振幅 {profile.kline_range_pct_20d:.1f}%")
    if profile.price_change_1m_pct is not None:
        parts.append(f"近 1 个月 {profile.price_change_1m_pct:+.1f}%")
    if profile.price_change_3m_pct is not None:
        parts.append(f"近 3 个月 {profile.price_change_3m_pct:+.1f}%")
    if profile.price_change_1y_pct is not None:
        parts.append(f"近 1 年 {profile.price_change_1y_pct:+.1f}%")
    return "；".join(parts) if parts else "无可用行情"


def _summarize_notes(hits: list[Hit]) -> str:
    if not hits:
        return "（未召回相关笔记）"
    lines = []
    for h in hits[:5]:
        lines.append(f"- {h.note_id}: {h.excerpt[:80]}")
    return "\n".join(lines)


def build_context(
    code: str,
    name: str | None,
    industry: str | None,
    profile: Profile,
    announcements: list[Announcement],
    news: list[NewsItem],
    hits: list[Hit],
) -> BriefContext:
    return BriefContext(
        ticker={"code": code, "name": name, "industry": industry},
        profile=profile.to_dict(),
        recent_kline_summary=_summarize_kline(profile),
        announcements=[
            {"date": a.publish_time.strftime("%Y-%m-%d"), "title": a.title, "kind": a.kind}
            for a in announcements[:10]
        ],
        news=[
            {"date": n.publish_time.strftime("%Y-%m-%d"), "title": n.title, "source": n.source}
            for n in news[:10]
        ],
        recalled_notes=[
            {
                "id": h.note_id,
                "excerpt": h.excerpt,
                "score": round(h.score, 3),
                "tickers": h.tickers,
                "tags": h.tags + h.themes,
            }
            for h in hits[:8]
        ],
        user_stance=_summarize_notes(hits),
    )


def render_dryrun_brief(ctx: BriefContext) -> str:
    """无 LLM 时用模板渲染出可读 markdown。"""
    p = ctx.profile
    lines: list[str] = []
    lines.append(f"# {ctx.ticker.get('name') or ctx.ticker['code']} ({ctx.ticker['code']}) 研究简报")
    lines.append("")
    lines.append("## 一、事实速览")
    lines.append(f"- 最新价：{_fmt(p.get('price'))}  ·  日内 {_fmt_pct(p.get('price_change_1d_pct'))}")
    lines.append(f"- 近期走势：{ctx.recent_kline_summary}")
    lines.append(
        f"- 估值：PE_TTM {_fmt(p.get('pe_ttm'))}（5Y 分位 {_fmt(p.get('pe_pct_5y'), suffix='%')}）"
        f"  ·  PB {_fmt(p.get('pb'))}（5Y 分位 {_fmt(p.get('pb_pct_5y'), suffix='%')}）"
        f"  ·  股息 {_fmt(p.get('dv_ratio'), suffix='%')}"
    )
    lines.append(
        f"- 财务：营收同比 {_fmt_pct(p.get('revenue_yoy_pct'))}"
        f"  ·  净利同比 {_fmt_pct(p.get('net_profit_yoy_pct'))}"
    )
    lines.append("")

    lines.append("## 二、近期动态")
    if ctx.announcements:
        lines.append("**公告**")
        for a in ctx.announcements:
            lines.append(f"- {a['date']}  {a['title']}")
    if ctx.news:
        lines.append("")
        lines.append("**新闻**")
        for n in ctx.news:
            lines.append(f"- {n['date']}  [{n.get('source', '')}] {n['title']}")
    if not ctx.announcements and not ctx.news:
        lines.append("（暂无公告与新闻）")
    lines.append("")

    lines.append("## 三、我的历史观点")
    lines.append(ctx.user_stance)
    lines.append("")

    lines.append("## 四、判断")
    lines.append("_dry-run 模式：无 LLM 综合推理。以下仅为客观事实拼装。_")
    lines.append("")

    lines.append("## 五、结论")
    lines.append("")
    lines.append("```json")
    lines.append('{')
    lines.append('  "action": "watch",')
    lines.append('  "size_pct": 0,')
    lines.append('  "confidence": 0.0,')
    lines.append('  "horizon_days": 30,')
    lines.append('  "rationale": "dry-run，未调用 LLM"')
    lines.append('}')
    lines.append("```")
    return "\n".join(lines)


def _fmt(v, suffix: str = "") -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.2f}{suffix}"
    return f"{v}{suffix}"


def _fmt_pct(v) -> str:
    if v is None:
        return "-"
    return f"{v:+.2f}%"
