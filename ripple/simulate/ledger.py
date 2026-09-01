"""组合与记账引擎：建组合、买、卖、维护持仓成本。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ripple.core.symbol import Symbol
from ripple.models import Portfolio, Position, Trade, session
from ripple.simulate.fees import compute_fees

DEFAULT_PORTFOLIO_ID = "main"
DEFAULT_CASH = 1_000_000.0


class TradeError(Exception):
    """交易被拒（资金不足/持仓不足/非整手等）。"""


@dataclass
class TradeReceipt:
    side: str
    code: str
    qty: int
    price: float
    fee: float
    cash_delta: float       # 现金变动（买为负，卖为正）
    realized_pnl: float | None
    cash_after: float
    avg_cost_after: float
    qty_after: int


def get_or_create_portfolio(pid: str = DEFAULT_PORTFOLIO_ID,
                            cash: float = DEFAULT_CASH,
                            name: str = "默认模拟组合") -> Portfolio:
    with session() as s:
        p = s.get(Portfolio, pid)
        if p is None:
            p = Portfolio(id=pid, name=name, cash=cash, init_cash=cash,
                          created=datetime.utcnow())
            s.add(p)
            s.commit()
            s.refresh(p)
        # detach 一份数据
        return Portfolio(id=p.id, name=p.name, cash=p.cash,
                         init_cash=p.init_cash, created=p.created)


def _get_position(s, pid: str, code: str) -> Position | None:
    return s.query(Position).filter_by(portfolio_id=pid, code=code).one_or_none()


def buy(code: str, qty: int, price: float, pid: str = DEFAULT_PORTFOLIO_ID,
        advice_id: str | None = None) -> TradeReceipt:
    sym = Symbol.parse(code)
    code = sym.code
    if qty <= 0 or qty % 100 != 0:
        raise TradeError(f"买入必须为 100 股整数倍，收到 {qty}")

    fees = compute_fees(price, qty, "buy")
    cost = price * qty + fees.total

    with session() as s:
        p = s.get(Portfolio, pid)
        if p is None:
            raise TradeError(f"组合 {pid} 不存在，请先 ripple sim init")
        if cost > p.cash + 1e-6:
            raise TradeError(f"现金不足：需 {cost:.2f}，仅有 {p.cash:.2f}")

        pos = _get_position(s, pid, code)
        if pos is None:
            pos = Position(portfolio_id=pid, code=code, qty=0, avg_cost=0.0)
            s.add(pos)
        # 移动加权平均成本（把费用摊进成本）
        old_cost_total = pos.avg_cost * pos.qty
        new_qty = pos.qty + qty
        new_avg = (old_cost_total + cost) / new_qty
        pos.qty = new_qty
        pos.avg_cost = round(new_avg, 4)
        pos.updated = datetime.utcnow()

        p.cash = round(p.cash - cost, 2)

        s.add(Trade(portfolio_id=pid, ticker=code, side="buy", price=price,
                    qty=qty, fee=fees.total, realized_pnl=None,
                    ts=datetime.utcnow(), advice_id=advice_id))
        s.commit()
        return TradeReceipt(
            side="buy", code=code, qty=qty, price=price, fee=fees.total,
            cash_delta=-cost, realized_pnl=None, cash_after=p.cash,
            avg_cost_after=pos.avg_cost, qty_after=pos.qty,
        )


def sell(code: str, qty: int, price: float, pid: str = DEFAULT_PORTFOLIO_ID,
         advice_id: str | None = None) -> TradeReceipt:
    sym = Symbol.parse(code)
    code = sym.code
    if qty <= 0 or qty % 100 != 0:
        raise TradeError(f"卖出必须为 100 股整数倍，收到 {qty}")

    fees = compute_fees(price, qty, "sell")
    proceeds = price * qty - fees.total

    with session() as s:
        p = s.get(Portfolio, pid)
        if p is None:
            raise TradeError(f"组合 {pid} 不存在，请先 ripple sim init")
        pos = _get_position(s, pid, code)
        if pos is None or pos.qty < qty:
            have = pos.qty if pos else 0
            raise TradeError(f"持仓不足：欲卖 {qty}，仅有 {have}")

        # 已实现盈亏 = 卖出净得 - 卖出量 × 单位成本
        realized = round(proceeds - qty * pos.avg_cost, 2)

        pos.qty -= qty
        if pos.qty == 0:
            pos.avg_cost = 0.0
        pos.updated = datetime.utcnow()

        p.cash = round(p.cash + proceeds, 2)

        s.add(Trade(portfolio_id=pid, ticker=code, side="sell", price=price,
                    qty=qty, fee=fees.total, realized_pnl=realized,
                    ts=datetime.utcnow(), advice_id=advice_id))
        # 清仓则删持仓行
        if pos.qty == 0:
            s.delete(pos)
        s.commit()
        return TradeReceipt(
            side="sell", code=code, qty=qty, price=price, fee=fees.total,
            cash_delta=proceeds, realized_pnl=realized, cash_after=p.cash,
            avg_cost_after=(pos.avg_cost if pos.qty else 0.0), qty_after=pos.qty,
        )


def positions(pid: str = DEFAULT_PORTFOLIO_ID) -> list[Position]:
    with session() as s:
        rows = s.query(Position).filter_by(portfolio_id=pid).all()
        return [Position(portfolio_id=r.portfolio_id, code=r.code, qty=r.qty,
                         avg_cost=r.avg_cost, updated=r.updated) for r in rows]


def trades(pid: str = DEFAULT_PORTFOLIO_ID, code: str | None = None) -> list[Trade]:
    with session() as s:
        q = s.query(Trade).filter_by(portfolio_id=pid)
        if code:
            q = q.filter_by(ticker=code)
        rows = q.order_by(Trade.ts).all()
        return [Trade(id=r.id, portfolio_id=r.portfolio_id, ticker=r.ticker,
                      side=r.side, price=r.price, qty=r.qty, fee=r.fee,
                      realized_pnl=r.realized_pnl, ts=r.ts, advice_id=r.advice_id)
                for r in rows]
