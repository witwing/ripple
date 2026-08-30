"""Provider 抽象与数据类。业务层只跟这里的类型打交道，不接触厂商原生字段。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Protocol, runtime_checkable

import pandas as pd


# ---- 统一返回结构（v0.3 定义）----

KLINE_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "turnover_pct"]


@dataclass
class TickerProfile:
    code: str
    name: str
    exchange: str | None = None
    board: str | None = None
    industry: str | None = None       # 行业中类，如 "白酒"
    industry_l1: str | None = None    # 一级行业，如 "主要消费" / "食品饮料与烟草"
    list_date: str | None = None      # YYYY-MM-DD
    total_mv: float | None = None
    float_mv: float | None = None
    main_business: str | None = None  # 主营业务一句话
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class FinancialMetrics:
    """单期财务综合指标（从 stock_financial_abstract 抽出的关键行）。"""
    code: str
    period: str                        # YYYYMMDD
    revenue: float | None = None
    net_profit: float | None = None
    net_profit_deducted: float | None = None  # 扣非
    revenue_yoy_pct: float | None = None
    net_profit_yoy_pct: float | None = None
    roe: float | None = None           # 净资产收益率
    roe_avg: float | None = None       # 加权平均 ROE
    gross_margin: float | None = None  # 销售毛利率
    net_margin: float | None = None    # 销售净利率
    debt_ratio: float | None = None    # 资产负债率
    ocf_to_revenue: float | None = None  # 经营现金流/营收
    eps: float | None = None
    bvps: float | None = None          # 每股净资产
    fetched_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Quote:
    code: str
    ts: datetime
    price: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    volume: float | None = None
    amount: float | None = None


@dataclass
class Valuation:
    code: str
    ts: datetime
    pe_ttm: float | None = None
    pb: float | None = None
    dv_ratio: float | None = None
    pe_pct_5y: float | None = None
    pb_pct_5y: float | None = None


@dataclass
class Announcement:
    code: str
    title: str
    url: str
    publish_time: datetime
    kind: str | None = None


@dataclass
class NewsItem:
    code: str
    title: str
    url: str
    publish_time: datetime
    source: str
    summary: str | None = None


@dataclass
class HealthStatus:
    provider: str
    ok: bool
    latency_ms: int
    message: str = ""
    checked_at: datetime = field(default_factory=datetime.utcnow)


# ---- Capability Protocols ----

@runtime_checkable
class BaseProvider(Protocol):
    name: str

    def health(self) -> HealthStatus: ...


@runtime_checkable
class MetaProvider(BaseProvider, Protocol):
    def profile(self, code: str) -> TickerProfile: ...


@runtime_checkable
class QuoteProvider(BaseProvider, Protocol):
    def daily_kline(self, code: str, start: date, end: date) -> pd.DataFrame: ...
    def snapshot(self, code: str) -> Quote: ...


@runtime_checkable
class FundamentalProvider(BaseProvider, Protocol):
    def financial_reports(
        self, code: str, kind: Literal["income", "balance", "cash"], periods: int = 8
    ) -> pd.DataFrame: ...
    def valuation(self, code: str) -> Valuation: ...


@runtime_checkable
class MetricsProvider(BaseProvider, Protocol):
    """财务综合指标：ROE / 毛利率 / 现金流比 / 负债率等。"""
    def financial_metrics(self, code: str, periods: int = 8) -> list[FinancialMetrics]: ...


@runtime_checkable
class IndexProvider(BaseProvider, Protocol):
    """大盘 / 行业指数日线。用于相对表现基准。"""
    def index_daily(self, index_code: str, start: date, end: date) -> pd.DataFrame: ...


@runtime_checkable
class DisclosureProvider(BaseProvider, Protocol):
    def announcements(self, code: str, since: date) -> list[Announcement]: ...


@runtime_checkable
class NewsProvider(BaseProvider, Protocol):
    def news(self, code: str, since: date, limit: int = 50) -> list[NewsItem]: ...


# 能力名 → Protocol，方便按字符串取
CAPABILITIES: dict[str, type] = {
    "meta": MetaProvider,
    "quote": QuoteProvider,
    "fundamental": FundamentalProvider,
    "metrics": MetricsProvider,
    "index": IndexProvider,
    "disclosure": DisclosureProvider,
    "news": NewsProvider,
}


class ProviderError(Exception):
    """所有 Provider 抛出的通用异常，装饰器捕获后决定重试/降级。"""


def empty_kline() -> pd.DataFrame:
    return pd.DataFrame({c: [] for c in KLINE_COLUMNS})


def normalize_kline(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """把厂商 DataFrame 规范到 KLINE_COLUMNS。缺失列填 NaN，多余列丢弃。"""
    if df is None or df.empty:
        return empty_kline()
    out = pd.DataFrame(index=range(len(df)))
    for col in KLINE_COLUMNS:
        out[col] = df[col] if col in df.columns else pd.NA
    return out
