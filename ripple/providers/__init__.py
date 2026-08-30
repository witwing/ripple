"""Providers 包。首次 import 时按 config 注册可用 provider。"""
from ripple.providers.base import (  # noqa: F401
    Announcement,
    BaseProvider,
    CAPABILITIES,
    DisclosureProvider,
    FinancialMetrics,
    FundamentalProvider,
    HealthStatus,
    IndexProvider,
    KLINE_COLUMNS,
    MetaProvider,
    MetricsProvider,
    NewsItem,
    NewsProvider,
    ProviderError,
    Quote,
    QuoteProvider,
    TickerProfile,
    Valuation,
    empty_kline,
    normalize_kline,
)
from ripple.providers.registry import registry  # noqa: F401
