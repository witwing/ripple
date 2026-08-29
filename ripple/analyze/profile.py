"""基本面画像 —— 纯 Python，不调 LLM。

输入是从 provider 拿到的原始数据（Quote / Valuation / 财报 DataFrame / K线 DataFrame），
输出是一个扁平字典，字段缺失时值为 None。业务层不猜。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

from ripple.providers.base import Quote, Valuation


@dataclass
class Profile:
    code: str
    name: str | None = None

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

    # 财务（TTM 或最近一期）
    revenue_yoy_pct: float | None = None
    net_profit_yoy_pct: float | None = None

    # 追加字段留白
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _pct_change(cur: float | None, base: float | None) -> float | None:
    if cur is None or base is None or base == 0:
        return None
    return round((cur - base) / base * 100, 2)


def _price_at_or_before(kline: pd.DataFrame, target: date) -> float | None:
    """在 K 线里取 target 日期或之前最近的一个 close。"""
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
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f


def _kline_range_pct(kline: pd.DataFrame, tail: int = 20) -> float | None:
    if kline is None or kline.empty or "close" not in kline.columns:
        return None
    tail_df = kline.tail(tail)
    closes = pd.to_numeric(tail_df["close"], errors="coerce").dropna()
    if closes.empty or closes.mean() == 0:
        return None
    return round((closes.max() - closes.min()) / closes.mean() * 100, 2)


def _yoy_from_income(df: pd.DataFrame, needle_candidates: list[str]) -> float | None:
    """在利润表 DataFrame 里找一行匹配 needle 的项目，取最近两期算同比。

    sina 返回的通常是"项目 + 多个报告期列"的宽表。
    """
    if df is None or df.empty:
        return None
    first_col = df.columns[0]
    for needle in needle_candidates:
        matches = df[df[first_col].astype(str).str.contains(needle, na=False)]
        if matches.empty:
            continue
        row = matches.iloc[0]
        # 报告期列（除首列外）
        period_cols = [c for c in df.columns[1:]]
        if len(period_cols) < 2:
            return None
        # 假定第一个报告期为最近期（sina 一般降序）
        try:
            cur = float(str(row[period_cols[0]]).replace(",", ""))
            prev_year = None
            # 找 4 个季度前作为同比基准
            for c in period_cols[1:]:
                try:
                    prev_year = float(str(row[c]).replace(",", ""))
                    break
                except (TypeError, ValueError):
                    continue
        except (TypeError, ValueError):
            return None
        return _pct_change(cur, prev_year)
    return None


def build_profile(
    code: str,
    name: str | None,
    quote: Quote | None,
    kline: pd.DataFrame | None,
    valuation: Valuation | None,
    income: pd.DataFrame | None,
) -> Profile:
    p = Profile(code=code, name=name)

    if quote:
        p.price = quote.price
        p.prev_close = quote.prev_close
        p.price_change_1d_pct = _pct_change(quote.price, quote.prev_close)

    if kline is not None and not kline.empty:
        today = date.today()
        latest = _price_at_or_before(kline, today)
        p.price_change_1m_pct = _pct_change(latest, _price_at_or_before(kline, today - timedelta(days=30)))
        p.price_change_3m_pct = _pct_change(latest, _price_at_or_before(kline, today - timedelta(days=90)))
        p.price_change_1y_pct = _pct_change(latest, _price_at_or_before(kline, today - timedelta(days=365)))
        p.kline_range_pct_20d = _kline_range_pct(kline)

    if valuation:
        p.pe_ttm = valuation.pe_ttm
        p.pb = valuation.pb
        p.dv_ratio = valuation.dv_ratio
        p.pe_pct_5y = valuation.pe_pct_5y
        p.pb_pct_5y = valuation.pb_pct_5y

    if income is not None:
        p.revenue_yoy_pct = _yoy_from_income(income, ["营业总收入", "营业收入"])
        p.net_profit_yoy_pct = _yoy_from_income(income, ["归属于母公司股东的净利润", "净利润"])

    return p
