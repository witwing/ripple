"""study 编排器：Fetch → Snapshot → Recall → Profile → Narrate → Advise。"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from sqlalchemy import select

from ripple.analyze.advisor import ParsedAdvice, parse_from_brief
from ripple.analyze.narrative import BriefContext, build_context, render_dryrun_brief
from ripple.analyze.profile import Profile, build_profile
from ripple.core import paths
from ripple.core.config import Config
from ripple.core.logger import get_logger
from ripple.core.symbol import Symbol
from ripple.models import Advice, Brief, Snapshot, Ticker, session
from ripple.notes import search
from ripple.notes.search import Hit
from ripple.providers.base import Announcement, NewsItem, Quote, Valuation
from ripple.providers.registry import registry

log = get_logger(__name__)

Narrator = Callable[[BriefContext], tuple[str, str]]  # returns (markdown, model_id)


@dataclass
class StudyResult:
    brief_id: str
    brief_path: Path
    advice_id: str
    advice: ParsedAdvice
    profile: Profile
    context: BriefContext


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


def _fetch_name_industry(code: str) -> tuple[str | None, str | None]:
    with session() as s:
        t = s.get(Ticker, code)
        if t:
            return t.name, t.industry
    # 现拉一次
    profile = _safe(registry.call, "meta", "profile", code)
    if profile:
        return profile.name, profile.industry
    return None, None


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
    quote: Quote | None = _safe(registry.call, "quote", "snapshot", code)
    kline = _safe(
        registry.call, "quote", "daily_kline", code,
        (date.today() - timedelta(days=400)), date.today(),
    )
    valuation: Valuation | None = _safe(registry.call, "fundamental", "valuation", code)
    income = _safe(registry.call, "fundamental", "financial_reports", code, "income", 8)
    since = date.today() - timedelta(days=90)
    announcements: list[Announcement] = _safe(registry.call, "disclosure", "announcements", code, since) or []
    news: list[NewsItem] = _safe(registry.call, "news", "news", code, since, 20) or []

    log.info("[2/6] Snapshot — 落库")
    if quote:
        _snapshot_row(code, "quote", {"price": quote.price, "prev_close": quote.prev_close}, "akshare")
    if valuation:
        _snapshot_row(code, "val", {"pe_ttm": valuation.pe_ttm, "pb": valuation.pb}, "akshare")

    log.info("[3/6] Recall — 检索历史笔记")
    name, industry = _fetch_name_industry(code)
    q = _recall_query(name, industry, code)
    hits: list[Hit] = search.recall(cfg, q, k=8)
    log.info(f"       召回 {len(hits)} 条")

    log.info("[4/6] Profile — 计算基本面画像")
    profile = build_profile(code, name, quote, kline, valuation, income)

    log.info("[5/6] Narrate — 生成简报")
    ctx = build_context(code, name, industry, profile, announcements, news, hits)
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
        profile=profile, context=ctx,
    )


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
