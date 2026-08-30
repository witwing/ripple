"""基本面画像 —— 纯 Python，不调 LLM。

输入：从 provider 拿到的原始数据；
输出：一个扁平 Profile，字段缺失时值为 None（业务层不猜）。

**原则**：这一层专门做"相对量 / 分位 / 环比"计算，把绝对数字变成
LLM 更易判断的相对数字（比"净利 445 亿"更好用的是"净利同比 -2%，5Y 分位 25%"）。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

from ripple.providers.base import FinancialMetrics, Quote, Valuation


@dataclass
class Profile:
    code: str
    name: str | None = None
    industry: str | None = None

    # 价格与走势
    price: float | None = None
    prev_close: float | None = None
    price_change_1d_pct: float | None = None
    price_change_1m_pct: float | None = None
    price_change_3m_pct: float | None = None
    price_change_1y_pct: float | None = None
    kline_range_pct_20d: float | None = None  # 近 20 日 (max-min)/mean

    # 估值
    pe_ttm: float | None = None
    pb: float | None = None
    dv_ratio: float | None = None
    pe_pct_5y: float | None = None
    pb_pct_5y: float | None = None

    # 财务（最近一期）
    revenue_yoy_pct: float | None = None
    net_profit_yoy_pct: float | None = None
    roe: float | None = None
    roe_avg: float | None = None
    gross_margin: float | None = None
    net_margin: float | None = None
    debt_ratio: float | None = None
    ocf_to_revenue: float | None = None  # 经营现金流/营收
    eps: float | None = None
    bvps: float | None = None

    # 财务趋势（环比 / 最近 4 期）
    roe_yoy_change_pp: float | None = None    # ROE 同比变化（百分点）
    net_margin_yoy_change_pp: float | None = None  # 净利率同比变化（百分点）

    # 相对表现（vs 指数）
    price_vs_hs300_1m_pp: float | None = None  # 近 1 月 vs 沪深300（百分点差）
    price_vs_hs300_3m_pp: float | None = None
    price_vs_hs300_1y_pp: float | None = None

    # 追加字段留白
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PeerRow:
    """同行对比表一行。"""
    code: str
    name: str | None
    pe_ttm: float | None
    pb: float | None
    roe: float | None
    price_change_1y_pct: float | None


# ---- helpers ----

def _pct_change(cur: float | None, base: float | None) -> float | None:
    if cur is None or base is None or base == 0:
        return None
    return round((cur - base) / base * 100, 2)


def _diff_pp(cur: float | None, base: float | None) -> float | None:
    """两个百分数字段的差（百分点），如 ROE 16.75 vs 17.3 → -0.55pp"""
    if cur is None or base is None:
        return None
    return round(cur - base, 2)


def _price_at_or_before(kline: pd.DataFrame, target: date) -> float | None:
    if kline is None or kline.empty or "date" not in kline.columns or "close" not in kline.columns:
        return None
    try:
        dates = pd.to_datetime(kline["date"])
    except Exception:
        return None
    ts = pd.Timestamp(target)
    mask = dates <= ts
    if not mask.any():
        return None
    row = kline[mask].iloc[-1]
    val = row.get("close")
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _kline_range_pct(kline: pd.DataFrame, tail: int = 20) -> float | None:
    if kline is None or kline.empty or "close" not in kline.columns:
        return None
    tail_df = kline.tail(tail)
    closes = pd.to_numeric(tail_df["close"], errors="coerce").dropna()
    if closes.empty or closes.mean() == 0:
        return None
    return round((closes.max() - closes.min()) / closes.mean() * 100, 2)


def _yoy_from_income(df: pd.DataFrame, needle_candidates: list[str]) -> float | None:
    """兼容旧路径：从利润表 sina 宽表算某项目最近同比。"""
    if df is None or df.empty:
        return None
    date_col = "报告日" if "报告日" in df.columns else df.columns[0]
    col_name = None
    for needle in needle_candidates:
        for c in df.columns:
            if needle in str(c):
                col_name = c
                break
        if col_name:
            break
    if not col_name:
        return None
    try:
        sorted_df = df.sort_values(date_col, ascending=False).reset_index(drop=True)
    except Exception:
        sorted_df = df
    if len(sorted_df) < 5:
        return None
    try:
        cur = float(str(sorted_df.iloc[0][col_name]).replace(",", ""))
        prev_year = float(str(sorted_df.iloc[4][col_name]).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return _pct_change(cur, prev_year)


def build_profile(
    code: str,
    name: str | None,
    industry: str | None,
    quote: Quote | None,
    kline: pd.DataFrame | None,
    valuation: Valuation | None,
    income: pd.DataFrame | None,
    metrics: list[FinancialMetrics] | None = None,
    index_kline: pd.DataFrame | None = None,
) -> Profile:
    """装 Profile。所有输入允许为 None，缺失字段留 None。"""
    p = Profile(code=code, name=name, industry=industry)

    if quote:
        p.price = quote.price
        p.prev_close = quote.prev_close
        p.price_change_1d_pct = _pct_change(quote.price, quote.prev_close)

    today = date.today()
    d30 = today - timedelta(days=30)
    d90 = today - timedelta(days=90)
    d365 = today - timedelta(days=365)

    latest_close = None
    if kline is not None and not kline.empty:
        latest_close = _price_at_or_before(kline, today)
        p.price_change_1m_pct = _pct_change(latest_close, _price_at_or_before(kline, d30))
        p.price_change_3m_pct = _pct_change(latest_close, _price_at_or_before(kline, d90))
        p.price_change_1y_pct = _pct_change(latest_close, _price_at_or_before(kline, d365))
        p.kline_range_pct_20d = _kline_range_pct(kline)

    if valuation:
        p.pe_ttm = valuation.pe_ttm
        p.pb = valuation.pb
        p.dv_ratio = valuation.dv_ratio
        p.pe_pct_5y = valuation.pe_pct_5y
        p.pb_pct_5y = valuation.pb_pct_5y

    # metrics 优先，income 表作 fallback（仅算营收/净利同比）
    if metrics:
        m0 = metrics[0]
        p.revenue_yoy_pct = m0.revenue_yoy_pct
        p.net_profit_yoy_pct = m0.net_profit_yoy_pct
        p.roe = m0.roe
        p.roe_avg = m0.roe_avg
        p.gross_margin = m0.gross_margin
        p.net_margin = m0.net_margin
        p.debt_ratio = m0.debt_ratio
        p.ocf_to_revenue = m0.ocf_to_revenue
        p.eps = m0.eps
        p.bvps = m0.bvps
        # 同比变化：找 4 期前
        if len(metrics) >= 5:
            m4 = metrics[4]
            p.roe_yoy_change_pp = _diff_pp(m0.roe, m4.roe)
            p.net_margin_yoy_change_pp = _diff_pp(m0.net_margin, m4.net_margin)
    elif income is not None:
        p.revenue_yoy_pct = _yoy_from_income(income, ["营业总收入", "营业收入"])
        p.net_profit_yoy_pct = _yoy_from_income(income, ["归属于母公司股东的净利润", "净利润"])

    # 相对指数：股票涨跌 - 指数涨跌，单位百分点
    if kline is not None and index_kline is not None and not index_kline.empty:
        idx_latest = _price_at_or_before(index_kline, today)
        # 用股价的涨跌 - 指数的涨跌
        for horizon_days, field_name in [(30, "price_vs_hs300_1m_pp"),
                                          (90, "price_vs_hs300_3m_pp"),
                                          (365, "price_vs_hs300_1y_pp")]:
            past = today - timedelta(days=horizon_days)
            stk_pct = _pct_change(latest_close, _price_at_or_before(kline, past))
            idx_pct = _pct_change(idx_latest, _price_at_or_before(index_kline, past))
            setattr(p, field_name, _diff_pp(stk_pct, idx_pct))

    return p
