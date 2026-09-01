"""Narrative：装配 LLM 上下文 + dry-run 时的模板渲染。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ripple.analyze.dashboard import (
    build_scores,
    build_signals,
    pct_bar,
    score_stars,
    signal_bar,
)
from ripple.analyze.profile import PeerRow, Profile
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
    peers: list[dict] = field(default_factory=list)
    relative_summary: str = ""
    capital_summary: str = ""    # 资金面 + 筹码变化的一行摘要
    consensus_summary: str = ""  # 卖方共识的一行摘要
    signals: list[dict] = field(default_factory=list)   # 信号灯 [{label, light, note}]
    scores: list[dict] = field(default_factory=list)    # 维度打分 [{dim, score, basis}]


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


def _summarize_relative(profile: Profile) -> str:
    parts = []
    if profile.price_vs_hs300_1m_pp is not None:
        parts.append(f"近 1 月 vs 沪深300 {profile.price_vs_hs300_1m_pp:+.1f}pp")
    if profile.price_vs_hs300_3m_pp is not None:
        parts.append(f"近 3 月 {profile.price_vs_hs300_3m_pp:+.1f}pp")
    if profile.price_vs_hs300_1y_pp is not None:
        parts.append(f"近 1 年 {profile.price_vs_hs300_1y_pp:+.1f}pp")
    return "；".join(parts) if parts else ""


def _summarize_capital(profile: Profile) -> str:
    parts = []
    if profile.margin_balance is not None:
        parts.append(f"融资余额 {profile.margin_balance / 1e8:.1f} 亿元（{profile.margin_balance_date}）")
    if profile.margin_buy is not None:
        parts.append(f"当日融资买入 {profile.margin_buy / 1e8:.2f} 亿")
    if profile.shareholder_count is not None:
        chg = f"{profile.shareholder_count_change_pct:+.1f}%" if profile.shareholder_count_change_pct is not None else "-"
        parts.append(f"股东户数 {profile.shareholder_count / 1e4:.1f} 万（环比 {chg}，截止 {profile.shareholder_period}）")
    if profile.fund_count is not None:
        chg = f"{profile.fund_change_pct:+.1f}%" if profile.fund_change_pct is not None else ""
        direction = profile.fund_change_direction or ""
        parts.append(f"公募 {profile.fund_count} 家持仓（{direction} {chg}）")
    return "；".join(parts) if parts else ""


def _summarize_consensus(profile: Profile) -> str:
    if profile.analyst_report_count is None:
        return ""
    parts = [f"近期 {profile.analyst_report_count} 份研报"]
    if profile.analyst_ratings:
        rt = " / ".join(f"{k} {v}" for k, v in profile.analyst_ratings.items())
        parts.append(rt)
    if profile.consensus_eps_next_year is not None:
        parts.append(f"明年 EPS 中位 {profile.consensus_eps_next_year:.2f}")
    if profile.consensus_pe_next_year is not None:
        parts.append(f"隐含 PE 中位 {profile.consensus_pe_next_year:.1f}")
    return "  ·  ".join(parts)


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
    peers: list[PeerRow] | None = None,
) -> BriefContext:
    return BriefContext(
        ticker={"code": code, "name": name, "industry": industry},
        profile=profile.to_dict(),
        recent_kline_summary=_summarize_kline(profile),
        relative_summary=_summarize_relative(profile),
        capital_summary=_summarize_capital(profile),
        consensus_summary=_summarize_consensus(profile),
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
        peers=[
            {
                "code": p.code, "name": p.name,
                "pe_ttm": p.pe_ttm, "pb": p.pb, "roe": p.roe,
                "price_change_1y_pct": p.price_change_1y_pct,
            }
            for p in (peers or [])
        ],
        signals=[{"label": s.label, "light": s.light, "note": s.note}
                 for s in build_signals(profile)],
        scores=[{"dim": d.dim, "score": d.score, "basis": d.basis}
                for d in build_scores(profile)],
    )


def render_dryrun_brief(ctx: BriefContext) -> str:
    """无 LLM 时用模板渲染出美化的 markdown 报告。"""
    p = ctx.profile
    L: list[str] = []

    # ── 标题 ──
    L.append(f"# {ctx.ticker.get('name') or ctx.ticker['code']} ({ctx.ticker['code']})")
    sub = ctx.ticker.get("industry") or ""
    L.append(f"> {sub}  ·  研究简报（dry-run）")
    L.append("")

    # ── 信号面板 ──
    if ctx.signals:
        L.append("## 📊 信号面板")
        L.append("")
        L.append("  ".join(f"{s['light']} {s['label']}" for s in ctx.signals))
        L.append("")
        L.append("| 维度 | 信号 | 说明 |")
        L.append("|---|:---:|---|")
        for s in ctx.signals:
            L.append(f"| {s['label']} | {s['light']} | {s['note']} |")
        L.append("")

    # ── 关键指标 + 分位条 ──
    L.append("## 一、关键指标")
    L.append("")
    L.append("| 指标 | 数值 | 5Y 分位 |")
    L.append("|---|---:|---|")
    L.append(f"| PE-TTM | {_fmt(p.get('pe_ttm'))} | {_bar(p.get('pe_pct_5y'))} |")
    L.append(f"| PB | {_fmt(p.get('pb'))} | {_bar(p.get('pb_pct_5y'))} |")
    L.append(f"| ROE | {_fmt(p.get('roe'), suffix='%')} | — |")
    L.append(f"| 毛利率 | {_fmt(p.get('gross_margin'), suffix='%')} | — |")
    L.append(f"| 净利率 | {_fmt(p.get('net_margin'), suffix='%')} | — |")
    L.append(f"| 经营现金流/营收 | {_fmt(p.get('ocf_to_revenue'))} | — |")
    L.append(f"| 资产负债率 | {_fmt(p.get('debt_ratio'), suffix='%')} | — |")
    L.append("")
    L.append(f"- **价格**：{_fmt(p.get('price'))}  ·  日内 {_fmt_pct(p.get('price_change_1d_pct'))}")
    L.append(f"- **走势**：{ctx.recent_kline_summary}")
    if ctx.relative_summary:
        L.append(f"- **相对沪深300**：{ctx.relative_summary}")
    L.append(
        f"- **成长**：营收同比 {_fmt_pct(p.get('revenue_yoy_pct'))}"
        f"  ·  净利同比 {_fmt_pct(p.get('net_profit_yoy_pct'))}"
        f"  ·  ROE 同比 {_fmt_pp(p.get('roe_yoy_change_pp'))}"
    )
    L.append("")

    # ── 同行对比 ──
    if ctx.peers:
        L.append("## 二、同行对比")
        L.append("")
        L.append("| 代码 | 名称 | PE_TTM | PB | ROE | 近1年 |")
        L.append("|---|---|---:|---:|---:|---:|")
        for row in ctx.peers:
            L.append(
                f"| {row['code']} | {row.get('name') or '-'} "
                f"| {_fmt(row.get('pe_ttm'))} | {_fmt(row.get('pb'))} "
                f"| {_fmt(row.get('roe'), suffix='%')} "
                f"| {_fmt_pct(row.get('price_change_1y_pct'))} |"
            )
        L.append("")

    # ── 资金面与共识 ──
    if ctx.capital_summary or ctx.consensus_summary:
        L.append("## 三、资金面与共识")
        if ctx.capital_summary:
            L.append(f"- **资金/筹码**：{ctx.capital_summary}")
        if ctx.consensus_summary:
            L.append(f"- **卖方共识**：{ctx.consensus_summary}")
        L.append("")

    # ── 近期动态 ──
    L.append("## 四、近期动态")
    if ctx.announcements:
        L.append("**公告**")
        for a in ctx.announcements[:8]:
            L.append(f"- {a['date']}  {a['title']}")
    if ctx.news:
        L.append("")
        L.append("**新闻**")
        for n in ctx.news[:8]:
            L.append(f"- {n['date']}  [{n.get('source', '')}] {n['title']}")
    if not ctx.announcements and not ctx.news:
        L.append("（暂无公告与新闻）")
    L.append("")

    # ── 历史观点 ──
    L.append("## 五、我的历史观点")
    L.append(ctx.user_stance)
    L.append("")

    # ── 价值评分 ──
    if ctx.scores:
        L.append("## 六、投资价值评分")
        L.append("")
        L.append("| 维度 | 评分 | 依据 |")
        L.append("|---|:---:|---|")
        for d in ctx.scores:
            L.append(f"| {d['dim']} | {score_stars(d['score'])} | {d['basis']} |")
        L.append("")

    # ── 短中长期洞察（dry-run 占位）──
    L.append("## 七、短/中/长期洞察")
    L.append("_dry-run 模式：无 LLM 推理。以下为结构占位。_")
    L.append("- **短期（1-3 月）**：见信号面板")
    L.append("- **中期（6-12 月）**：见成长与资金面")
    L.append("- **长期（1-3 年）**：见质量与估值分位")
    L.append("")

    # ── 结论 ──
    L.append("## 八、结论")
    L.append("")
    L.append("```json")
    L.append('{')
    L.append('  "action": "watch",')
    L.append('  "size_pct": 0,')
    L.append('  "confidence": 0.0,')
    L.append('  "horizon_days": 30,')
    L.append('  "rationale": "dry-run，未调用 LLM"')
    L.append('}')
    L.append("```")
    return "\n".join(L)


def _bar(pct) -> str:
    return pct_bar(pct if isinstance(pct, (int, float)) else None)


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


def _fmt_pp(v) -> str:
    if v is None:
        return "-"
    return f"{v:+.2f}pp"
