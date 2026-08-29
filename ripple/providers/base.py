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
    industry: str | None = None
    list_date: str | None = None  # YYYY-MM-DD
    total_mv: float | None = None
    float_mv: float | None = None
    updated_at: datetime = field(default_factory=datetime.utcnow)


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
