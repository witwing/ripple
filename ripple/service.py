"""Service 层：框架无关的业务函数，返回纯 dict/list。

CLI 和 Web API 都调这里，保证行为一致。不 import typer / fastapi。
这一层是"防锁死"的关键：将来换任何前端，只要这层稳定即可。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from ripple.core import paths
from ripple.core.config import Config, load as load_config
from ripple.core.symbol import Symbol
from ripple.data import universe
from ripple.models import Advice, Brief, Ticker, Watch, session
from ripple.simulate import ledger, report


# ---- 自选池 ----

def list_watch() -> list[dict]:
    with session() as s:
        watches = s.query(Watch).order_by(Watch.added_at).all()
        tickers = {t.code: t for t in s.query(Ticker).all()}
        # 最新 advice
        out = []
        for w in watches:
            t = tickers.get(w.code)
            adv = s.execute(
                select(Advice).where(Advice.ticker == w.code)
                .order_by(Advice.created.desc())
            ).scalars().first()
            out.append({
                "code": w.code,
                "name": t.name if t else None,
                "industry": t.industry if t else None,
                "added_at": w.added_at.strftime("%Y-%m-%d"),
                "last_action": adv.action if adv else None,
                "last_confidence": adv.confidence if adv else None,
                "last_rationale": adv.rationale if adv else None,
                "last_at": adv.created.strftime("%Y-%m-%d %H:%M") if adv else None,
            })
        return out


def add_watch(code: str) -> dict:
    code = Symbol.parse(code).code
    with session() as s:
        if s.get(Watch, code) is None:
            s.add(Watch(code=code, added_at=datetime.utcnow()))
            s.commit()
    # 补 ticker 元信息（复用 provider）
    try:
        from ripple.providers.registry import registry
        cfg = load_config()
        if not registry._chains:
            registry.load_from_config(cfg)
        prof = registry.call("meta", "profile", code)
        with session() as s:
            t = s.get(Ticker, code) or Ticker(code=code)
            t.name, t.industry = prof.name, prof.industry
            t.exchange, t.board, t.list_date = prof.exchange, prof.board, prof.list_date
            t.updated_at = datetime.utcnow()
            s.merge(t)
            s.commit()
    except Exception:
        pass
    return {"code": code, "ok": True}


def remove_watch(code: str) -> dict:
    code = Symbol.parse(code).code
    with session() as s:
        w = s.get(Watch, code)
        if w:
            s.delete(w)
            s.commit()
    return {"code": code, "ok": True}


# ---- 搜索 ----

def search_stocks(query: str, limit: int = 20) -> list[dict]:
    rows = universe.search(query, limit=limit)
    return [{"code": r.code, "name": r.name, "pinyin": r.pinyin,
             "exchange": r.exchange, "board": r.board, "industry": r.industry}
            for r in rows]


def universe_status() -> dict:
    return {"count": universe.count()}


# ---- 个股报告 ----

def stock_reports(code: str) -> dict:
    code = Symbol.parse(code).code
    rdir = paths.report_dir(code)
    reports = []
    if rdir.exists():
        for md in sorted(rdir.glob("*.md"), reverse=True):
            if md.stem == "latest":
                continue
            png = md.with_suffix(".png")
            reports.append({
                "ts": md.stem,
                "md": md.name,
                "png": png.name if png.exists() else None,
            })
    latest_md = rdir / "latest.md"
    with session() as s:
        t = s.get(Ticker, code)
    return {
        "code": code,
        "name": t.name if t else None,
        "industry": t.industry if t else None,
        "has_latest": latest_md.exists(),
        "latest_digest": _extract_digest(latest_md) if latest_md.exists() else None,
        "reports": reports,
    }


def _extract_digest(md_path) -> str | None:
    """从简报 md 里抽判断章节（复用 digest 的思路，简版）。"""
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError:
        return None
    # 去 frontmatter
    if text.startswith("---"):
        text = text.split("---", 2)[-1]
    return text.strip()


# ---- 模拟组合 ----

def portfolio_status() -> dict | None:
    rep = report.build_report()
    if rep is None:
        return None
    return {
        "name": rep.name, "cash": rep.cash, "init_cash": rep.init_cash,
        "nav": rep.nav, "holdings_value": rep.holdings_value,
        "total_return_pct": rep.total_return_pct,
        "realized_pnl_total": rep.realized_pnl_total,
        "unrealized_pnl_total": rep.unrealized_pnl_total,
        "holdings": [
            {"code": h.code, "qty": h.qty, "avg_cost": h.avg_cost,
             "last_price": h.last_price, "market_value": h.market_value,
             "unrealized_pnl": h.unrealized_pnl, "unrealized_pct": h.unrealized_pct}
            for h in rep.holdings
        ],
    }


def portfolio_trades(code: str | None = None) -> list[dict]:
    return [
        {"ts": t.ts.strftime("%Y-%m-%d %H:%M"), "side": t.side, "code": t.ticker,
         "price": t.price, "qty": t.qty, "fee": t.fee,
         "realized_pnl": t.realized_pnl, "advice_id": t.advice_id}
        for t in ledger.trades(code=code)
    ]


def sim_buy(code: str, qty: int, price: float | None, advice_id: str | None = None) -> dict:
    px = price if price is not None else _live_price(code)
    r = ledger.buy(code, qty, px, advice_id=advice_id)
    return _receipt_dict(r)


def sim_sell(code: str, qty: int, price: float | None, advice_id: str | None = None) -> dict:
    px = price if price is not None else _live_price(code)
    r = ledger.sell(code, qty, px, advice_id=advice_id)
    return _receipt_dict(r)


def sim_init(cash: float = ledger.DEFAULT_CASH) -> dict:
    p = ledger.get_or_create_portfolio(cash=cash)
    return {"id": p.id, "name": p.name, "cash": p.cash}


def _live_price(code: str) -> float:
    from ripple.providers.registry import registry
    cfg = load_config()
    if not registry._chains:
        registry.load_from_config(cfg)
    q = registry.call("quote", "snapshot", code)
    if not q or not q.price:
        raise ValueError(f"取不到 {code} 现价，请显式传 price")
    return q.price


def _receipt_dict(r) -> dict:
    return {"side": r.side, "code": r.code, "qty": r.qty, "price": r.price,
            "fee": r.fee, "realized_pnl": r.realized_pnl,
            "cash_after": r.cash_after, "avg_cost_after": r.avg_cost_after,
            "qty_after": r.qty_after}


# ---- 监控 ----

def recent_triggers(days: int = 7) -> list[dict]:
    from datetime import timedelta

    from ripple.models import TriggerLog
    cutoff = datetime.utcnow() - timedelta(days=days)
    with session() as s:
        rows = s.execute(
            select(TriggerLog).where(TriggerLog.created >= cutoff)
            .order_by(TriggerLog.created.desc())
        ).scalars().all()
        tickers = {t.code: t for t in s.query(Ticker).all()}
        return [
            {"code": r.code, "name": tickers[r.code].name if r.code in tickers else None,
             "rule": r.rule, "reason": r.reason,
             "at": r.created.strftime("%Y-%m-%d %H:%M")}
            for r in rows
        ]


def monitor_config() -> dict:
    cfg = load_config()
    return {
        "feishu_webhook_set": bool(cfg.get("monitor.feishu_webhook")),
        "dedup_days": cfg.get("monitor.dedup_days", 3),
        "rules": cfg.get("monitor.rules", {}),
    }
