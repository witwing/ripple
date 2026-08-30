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


# ---- Capital flow / margin ----

@dataclass
class MarginSnapshot:
    """两融最新一天。"""
    code: str
    date: str                    # YYYYMMDD
    margin_balance: float | None = None      # 融资余额 (元)
    margin_buy: float | None = None          # 融资买入额
    short_balance: float | None = None       # 融券余额
    short_sell_volume: float | None = None   # 融券卖出量


@dataclass
class ShareholderSnapshot:
    """股东户数最近一期 + 环比。"""
    code: str
    period: str                              # YYYY-MM-DD
    count: int | None = None                 # 股东户数
    count_change_pct: float | None = None    # 环比 %
    holdings_per_account: float | None = None  # 户均持股市值 (元)


# ---- Institution ----

@dataclass
class FundHoldingSummary:
    """公募重仓单期汇总。"""
    code: str
    period: str                              # YYYYMMDD
    fund_count: int | None = None            # 持有基金家数
    total_shares: float | None = None        # 持股总数
    holdings_value: float | None = None      # 持股市值 (元)
    change_direction: str | None = None      # 加仓 / 减仓
    change_pct: float | None = None          # 持股变动比例


# ---- Research ----

@dataclass
class ResearchReport:
    code: str
    title: str
    org: str
    rating: str | None = None                # 买入 / 增持 / 中性 / 减持
    date: str | None = None                  # YYYY-MM-DD
    eps_next_year: float | None = None       # 明年 EPS 预测
    pe_next_year: float | None = None
    eps_2y: float | None = None              # 后年
    pe_2y: float | None = None


@dataclass
class ResearchConsensus:
    """卖方一致预期：把 N 份研报的 EPS 预测聚合。"""
    code: str
    report_count: int = 0                    # 覆盖研报数
    ratings: dict[str, int] = field(default_factory=dict)  # {"买入": 5, "增持": 2, ...}
    eps_next_year_median: float | None = None
    eps_next_year_min: float | None = None
    eps_next_year_max: float | None = None
    pe_next_year_median: float | None = None


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


@runtime_checkable
class CapitalFlowProvider(BaseProvider, Protocol):
    """资金面：融资融券 + 股东户数（散户/机构筹码变化）。"""
    def margin_snapshot(self, code: str) -> MarginSnapshot | None: ...
    def shareholder_count(self, code: str) -> ShareholderSnapshot | None: ...


@runtime_checkable
class InstitutionProvider(BaseProvider, Protocol):
    """机构持仓：公募基金重仓。"""
    def fund_holdings(self, code: str) -> FundHoldingSummary | None: ...


@runtime_checkable
class ResearchProvider(BaseProvider, Protocol):
    """卖方研报 + 一致预期。"""
    def research_reports(self, code: str, limit: int = 20) -> list[ResearchReport]: ...
    def consensus(self, code: str) -> ResearchConsensus: ...


# 能力名 → Protocol，方便按字符串取
CAPABILITIES: dict[str, type] = {
    "meta": MetaProvider,
    "quote": QuoteProvider,
    "fundamental": FundamentalProvider,
    "metrics": MetricsProvider,
    "index": IndexProvider,
    "disclosure": DisclosureProvider,
    "news": NewsProvider,
    "capital": CapitalFlowProvider,
    "institution": InstitutionProvider,
    "research": ResearchProvider,
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
