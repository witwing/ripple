"""净值 mark-to-market + 组合报告。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from ripple.core.logger import get_logger
from ripple.models import NavPoint, Portfolio, session
from ripple.simulate import ledger
from ripple.providers.registry import registry

log = get_logger(__name__)


@dataclass
class HoldingView:
    code: str
    qty: int
    avg_cost: float
    last_price: float | None
    market_value: float
    unrealized_pnl: float | None
    unrealized_pct: float | None


@dataclass
class PortfolioReport:
    pid: str
    name: str
    cash: float
    init_cash: float
    holdings: list[HoldingView] = field(default_factory=list)
    holdings_value: float = 0.0
    nav: float = 0.0
    total_return_pct: float | None = None
    realized_pnl_total: float = 0.0
    unrealized_pnl_total: float = 0.0


def _last_price(code: str) -> float | None:
    q = None
    try:
        q = registry.call("quote", "snapshot", code)
    except Exception as e:  # noqa: BLE001
        log.warning(f"取 {code} 现价失败：{e}")
        return None
    return q.price if q else None


def build_report(pid: str = ledger.DEFAULT_PORTFOLIO_ID,
                 price_lookup=None) -> PortfolioReport | None:
    """price_lookup(code)->float|None 可注入（测试用）；默认走 quote provider。"""
    price_lookup = price_lookup or _last_price
    with session() as s:
        p = s.get(Portfolio, pid)
        if p is None:
            return None
        rep = PortfolioReport(pid=p.id, name=p.name, cash=p.cash, init_cash=p.init_cash)

    # 已实现盈亏合计
    realized = 0.0
    for t in ledger.trades(pid):
        if t.realized_pnl is not None:
            realized += t.realized_pnl
    rep.realized_pnl_total = round(realized, 2)

    holdings_value = 0.0
    unreal = 0.0
    for pos in ledger.positions(pid):
        last = price_lookup(pos.code)
        mv = (last or pos.avg_cost) * pos.qty
        upnl = (last - pos.avg_cost) * pos.qty if last is not None else None
        upct = ((last / pos.avg_cost - 1) * 100) if (last and pos.avg_cost) else None
        holdings_value += mv
        if upnl is not None:
            unreal += upnl
        rep.holdings.append(HoldingView(
            code=pos.code, qty=pos.qty, avg_cost=round(pos.avg_cost, 3),
            last_price=last, market_value=round(mv, 2),
            unrealized_pnl=round(upnl, 2) if upnl is not None else None,
            unrealized_pct=round(upct, 2) if upct is not None else None,
        ))

    rep.holdings_value = round(holdings_value, 2)
    rep.unrealized_pnl_total = round(unreal, 2)
    rep.nav = round(rep.cash + holdings_value, 2)
    if rep.init_cash:
        rep.total_return_pct = round((rep.nav / rep.init_cash - 1) * 100, 2)
    return rep


def snapshot_nav(pid: str = ledger.DEFAULT_PORTFOLIO_ID,
                 price_lookup=None) -> NavPoint | None:
    """把当前净值落一个 nav_point。"""
    rep = build_report(pid, price_lookup=price_lookup)
    if rep is None:
        return None
    today = date.today().strftime("%Y-%m-%d")
    with session() as s:
        np = NavPoint(portfolio_id=pid, date=today, nav=rep.nav,
                      cash=rep.cash, holdings_value=rep.holdings_value,
                      ts=datetime.utcnow())
        s.add(np)
        s.commit()
        # 读出字段后再返回 detached 副本，避免 session 关闭后访问触发懒加载
        return NavPoint(id=np.id, portfolio_id=np.portfolio_id, date=np.date,
                        nav=np.nav, cash=np.cash, holdings_value=np.holdings_value,
                        ts=np.ts)


def nav_series(pid: str = ledger.DEFAULT_PORTFOLIO_ID) -> list[NavPoint]:
    with session() as s:
        rows = s.query(NavPoint).filter_by(portfolio_id=pid).order_by(NavPoint.ts).all()
        return [NavPoint(id=r.id, portfolio_id=r.portfolio_id, date=r.date,
                         nav=r.nav, cash=r.cash, holdings_value=r.holdings_value,
                         ts=r.ts) for r in rows]
