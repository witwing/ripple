"""study 编排器：Fetch → Snapshot → Recall → Profile → Narrate → Advise。"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from sqlalchemy import select

from ripple.analyze.advisor import ParsedAdvice, parse_from_brief
from ripple.analyze.digest import build_digest
from ripple.analyze.narrative import BriefContext, build_context, render_dryrun_brief
from ripple.analyze.peers import peers_of
from ripple.analyze.profile import PeerRow, Profile, build_profile
from ripple.core import paths
from ripple.core.config import Config
from ripple.core.logger import get_logger
from ripple.core.symbol import Symbol
from ripple.models import Advice, Brief, Snapshot, Ticker, session
from ripple.notes import search
from ripple.notes.search import Hit
from ripple.providers.base import (
    Announcement,
    FinancialMetrics,
    FundHoldingSummary,
    MarginSnapshot,
    NewsItem,
    Quote,
    ResearchConsensus,
    ShareholderSnapshot,
    TickerProfile,
    Valuation,
)
from ripple.providers.registry import registry

log = get_logger(__name__)

Narrator = Callable[[BriefContext], tuple[str, str]]  # returns (markdown, model_id)

# 相对基准指数（沪深300）
HS300 = "sh000300"


@dataclass
class StudyResult:
    brief_id: str
    brief_path: Path
    advice_id: str
    advice: ParsedAdvice
    profile: Profile
    context: BriefContext
    chart_path: Path | None = None
    markdown: str = ""       # 完整简报正文（不含 frontmatter）
    digest: str = ""         # 精简判断文字（配图用）


def _safe(fn: Callable, *args, **kwargs):
    """吞掉 provider 抛的异常，返回 None，让 study 能跑完。"""
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        log.warning(f"provider call 失败：{e}")
        return None


def _snapshot_row(code: str, kind: str, payload: dict, source: str):
    with session() as s:
        s.add(Snapshot(code=code, ts=datetime.utcnow(), kind=kind, payload_json=payload, source=source))
        s.commit()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"


def _brief_path(code: str, now: datetime) -> Path:
    return paths.briefs_dir() / now.strftime("%Y%m%d") / f"{code}_{now.strftime('%H%M%S')}.md"


def _recall_query(name: str | None, industry: str | None, code: str) -> str:
    parts = [code]
    if name:
        parts.append(name)
    if industry:
        parts.append(industry)
    return " ".join(parts)


def _fetch_meta(code: str) -> TickerProfile | None:
    """始终优先 provider 取（因为 profile 现在含更多字段）；DB 里的当缓存。"""
    prof = _safe(registry.call, "meta", "profile", code)
    if prof:
        # 落 ticker 表方便 watch list 展示
        with session() as s:
            t = s.get(Ticker, code)
            if t is None:
                t = Ticker(code=code)
                s.add(t)
            t.name = prof.name
            t.exchange = prof.exchange
            t.board = prof.board
            t.industry = prof.industry
            t.list_date = prof.list_date
            t.meta_json = {
                "industry_l1": prof.industry_l1,
                "total_mv": prof.total_mv,
                "float_mv": prof.float_mv,
                "main_business": prof.main_business,
            }
            t.updated_at = datetime.utcnow()
            s.commit()
        return prof
    # 兜底：从 DB 拉
    with session() as s:
        t = s.get(Ticker, code)
        if t:
            return TickerProfile(code=t.code, name=t.name or code, exchange=t.exchange,
                                 board=t.board, industry=t.industry, list_date=t.list_date)
    return None


def _build_peers_table(self_code: str, industry: str | None,
                       self_profile: Profile) -> list[PeerRow]:
    """为每个同行 code 拉 valuation + 最新价，装 PeerRow 列表；自身放最前。"""
    peer_codes = peers_of(industry, self_code=self_code, limit=4)
    if not peer_codes:
        return []
    rows: list[PeerRow] = []
    for pc in peer_codes:
        if pc == self_code:
            # 自身用已算的 profile
            rows.append(PeerRow(
                code=pc, name=self_profile.name,
                pe_ttm=self_profile.pe_ttm, pb=self_profile.pb, roe=self_profile.roe,
                price_change_1y_pct=self_profile.price_change_1y_pct,
            ))
            continue
        val = _safe(registry.call, "fundamental", "valuation", pc)
        metrics_list = _safe(registry.call, "metrics", "financial_metrics", pc, 5) or []
        # 简单拿最近一年涨跌
        kline = _safe(
            registry.call, "quote", "daily_kline", pc,
            (date.today() - timedelta(days=400)), date.today(),
        )
        change_1y = None
        if kline is not None and not kline.empty and "close" in kline.columns:
            import pandas as pd
            try:
                dates = pd.to_datetime(kline["date"])
                latest = float(kline["close"].iloc[-1])
                past_mask = dates <= pd.Timestamp(date.today() - timedelta(days=365))
                if past_mask.any():
                    past = float(kline[past_mask]["close"].iloc[-1])
                    if past:
                        change_1y = round((latest - past) / past * 100, 2)
            except Exception:
                pass
        # 名字：直接调一次 meta.profile（多数已缓存）
        peer_meta = _safe(registry.call, "meta", "profile", pc)
        rows.append(PeerRow(
            code=pc,
            name=peer_meta.name if peer_meta else pc,
            pe_ttm=val.pe_ttm if val else None,
            pb=val.pb if val else None,
            roe=metrics_list[0].roe if metrics_list else None,
            price_change_1y_pct=change_1y,
        ))
    return rows


def study(
    cfg: Config,
    code: str,
    *,
    refresh: bool = False,
    narrator: Narrator | None = None,
) -> StudyResult:
    """跑一次完整 study。narrator 为 None 时使用 dry-run 模板渲染。"""
    sym = Symbol.parse(code)
    code = sym.code
    now = datetime.now().astimezone()

    log.info(f"[1/6] Fetch — 拉取 {code} 数据")
    meta: TickerProfile | None = _fetch_meta(code)
    name = meta.name if meta else code
    industry = meta.industry if meta else None

    quote: Quote | None = _safe(registry.call, "quote", "snapshot", code)
    kline = _safe(
        registry.call, "quote", "daily_kline", code,
        (date.today() - timedelta(days=400)), date.today(),
    )
    valuation: Valuation | None = _safe(registry.call, "fundamental", "valuation", code)
    income = _safe(registry.call, "fundamental", "financial_reports", code, "income", 8)
    metrics: list[FinancialMetrics] = _safe(registry.call, "metrics", "financial_metrics", code, 8) or []
    since = date.today() - timedelta(days=90)
    announcements: list[Announcement] = _safe(registry.call, "disclosure", "announcements", code, since) or []
    news: list[NewsItem] = _safe(registry.call, "news", "news", code, since, 20) or []
    # 相对指数
    index_kline = _safe(
        registry.call, "index", "index_daily", HS300,
        (date.today() - timedelta(days=400)), date.today(),
    )
    # 资金面
    margin: MarginSnapshot | None = _safe(registry.call, "capital", "margin_snapshot", code)
    shareholders: ShareholderSnapshot | None = _safe(
        registry.call, "capital", "shareholder_count", code
    )
    # 机构
    fund_holdings: FundHoldingSummary | None = _safe(
        registry.call, "institution", "fund_holdings", code
    )
    # 卖方
    consensus: ResearchConsensus | None = _safe(registry.call, "research", "consensus", code)

    log.info("[2/6] Snapshot — 落库")
    if quote:
        _snapshot_row(code, "quote", {"price": quote.price, "prev_close": quote.prev_close}, "akshare")
    if valuation:
        _snapshot_row(code, "val", {"pe_ttm": valuation.pe_ttm, "pb": valuation.pb,
                                     "pe_pct_5y": valuation.pe_pct_5y}, "akshare")
    if metrics:
        _snapshot_row(code, "fin", {"period": metrics[0].period, "roe": metrics[0].roe,
                                    "gross_margin": metrics[0].gross_margin,
                                    "net_margin": metrics[0].net_margin,
                                    "debt_ratio": metrics[0].debt_ratio}, "akshare")
    if margin:
        _snapshot_row(code, "margin", {"date": margin.date, "balance": margin.margin_balance}, "akshare")
    if fund_holdings:
        _snapshot_row(code, "fund", {
            "period": fund_holdings.period, "count": fund_holdings.fund_count,
            "value": fund_holdings.holdings_value, "direction": fund_holdings.change_direction,
            "change_pct": fund_holdings.change_pct,
        }, "akshare")
    if consensus and consensus.report_count > 0:
        _snapshot_row(code, "consensus", {
            "report_count": consensus.report_count, "ratings": consensus.ratings,
            "eps_next_year_median": consensus.eps_next_year_median,
            "pe_next_year_median": consensus.pe_next_year_median,
        }, "akshare")

    log.info("[3/6] Recall — 检索历史笔记")
    q = _recall_query(name, industry, code)
    hits: list[Hit] = search.recall(cfg, q, k=8)
    log.info(f"       召回 {len(hits)} 条")

    log.info("[4/6] Profile — 计算基本面画像（含相对指数）")
    profile = build_profile(
        code=code, name=name, industry=industry,
        quote=quote, kline=kline, valuation=valuation,
        income=income, metrics=metrics, index_kline=index_kline,
        margin=margin, shareholders=shareholders,
        fund_holdings=fund_holdings, consensus=consensus,
        list_date=(meta.list_date if meta else None),
    )

    log.info("[4b/6] Peers — 装同行对比表")
    peers = _build_peers_table(code, industry, profile)
    log.info(f"        {len(peers)} 家同行")

    log.info("[5/6] Narrate — 生成简报")
    ctx = build_context(code, name, industry, profile, announcements, news, hits, peers=peers)
    if narrator is None:
        markdown = render_dryrun_brief(ctx)
        model_id = "dry-run"
        llm_mode = "dry-run"
    else:
        markdown, model_id = narrator(ctx)
        llm_mode = "live"

    brief_id = _new_id("brief")
    brief_path = _brief_path(code, now)
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = _brief_frontmatter(
        brief_id=brief_id, ticker=code, name=name, now=now,
        model=model_id, llm_mode=llm_mode, cited=[h.note_id for h in hits],
    )
    brief_path.write_text(frontmatter + "\n" + markdown, encoding="utf-8")

    log.info("[5b/6] Chart — 渲染可视化仪表盘")
    chart_path = _render_chart(code, now, profile, peers, kline, index_kline)

    log.info("[6/6] Advise — 提取结论")
    parsed = parse_from_brief(markdown)
    advice_id = _new_id("adv")

    with session() as s:
        s.add(Brief(
            id=brief_id, ticker=code, created=datetime.utcnow(),
            model=model_id, path=str(brief_path),
            cited_note_ids=[h.note_id for h in hits],
        ))
        s.add(Advice(
            id=advice_id, brief_id=brief_id, ticker=code,
            action=parsed.action, size_pct=parsed.size_pct,
            confidence=parsed.confidence, rationale=parsed.rationale,
            created=datetime.utcnow(),
        ))
        s.commit()

    return StudyResult(
        brief_id=brief_id, brief_path=brief_path,
        advice_id=advice_id, advice=parsed,
        profile=profile, context=ctx, chart_path=chart_path,
        markdown=markdown,
        digest=build_digest(markdown, parsed, name or code, code),
    )


def _render_chart(code, now, profile, peers, kline, index_kline):
    """渲染仪表盘 PNG。失败不阻断 study，返回 None。"""
    try:
        import pandas as pd

        from ripple.analyze.render import render_dashboard

        dates = closes = idx_closes = None
        # 近一年走势序列
        if kline is not None and not kline.empty and "close" in kline.columns:
            k = kline.copy()
            try:
                k["date"] = pd.to_datetime(k["date"])
                one_year = pd.Timestamp(now.date()) - pd.Timedelta(days=365)
                k = k[k["date"] >= one_year]
            except Exception:
                pass
            closes = [float(c) for c in k["close"].tolist() if c == c]
            dates = list(range(len(closes)))
            # 对齐指数：取相同长度尾部
            if index_kline is not None and not index_kline.empty and "close" in index_kline.columns:
                ik = index_kline.copy()
                try:
                    ik["date"] = pd.to_datetime(ik["date"])
                    ik = ik[ik["date"] >= one_year]
                except Exception:
                    pass
                ic = [float(c) for c in ik["close"].tolist() if c == c]
                # 截齐到相同长度
                n = min(len(closes), len(ic))
                if n > 1:
                    closes = closes[-n:]
                    idx_closes = ic[-n:]
                    dates = list(range(n))
        chart_dir = paths.briefs_dir() / now.strftime("%Y%m%d")
        chart_dir.mkdir(parents=True, exist_ok=True)
        out = chart_dir / f"{code}_{now.strftime('%H%M%S')}.png"
        return render_dashboard(profile, peers, dates, closes, idx_closes, out_path=out)
    except Exception as e:  # noqa: BLE001
        log.warning(f"仪表盘渲染失败：{e}")
        return None


def _brief_frontmatter(*, brief_id: str, ticker: str, name: str | None,
                       now: datetime, model: str, llm_mode: str, cited: list[str]) -> str:
    lines = ["---"]
    lines.append(f"id: {brief_id}")
    lines.append(f"ticker: {ticker}")
    if name:
        lines.append(f"name: {name}")
    lines.append(f"created: {now.isoformat()}")
    lines.append(f"model: {model}")
    lines.append(f"llm_mode: {llm_mode}")
    cited_list = "[" + ", ".join(cited) + "]" if cited else "[]"
    lines.append(f"cited_note_ids: {cited_list}")
    lines.append("---")
    return "\n".join(lines)
