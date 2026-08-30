"""study 编排端到端测试：用假 provider，验证整个链路和 dry-run 渲染。"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from ripple.analyze.study import study
from ripple.core.config import load
from ripple.providers.base import (
    Announcement,
    FinancialMetrics,
    FundHoldingSummary,
    HealthStatus,
    MarginSnapshot,
    NewsItem,
    Quote,
    ResearchConsensus,
    ShareholderSnapshot,
    TickerProfile,
    Valuation,
)
from ripple.providers.registry import registry


class FakeAll:
    """一个 fake provider 兼所有 capability。"""
    name = "fake"

    def health(self) -> HealthStatus:
        return HealthStatus(provider=self.name, ok=True, latency_ms=1)

    def profile(self, code: str) -> TickerProfile:
        return TickerProfile(code=code, name="贵州茅台", industry="白酒",
                             industry_l1="食品饮料", exchange="SH", board="MAIN",
                             list_date="2001-08-27", main_business="酿造和销售")

    def snapshot(self, code: str) -> Quote:
        return Quote(code=code, ts=datetime.utcnow(), price=1500.0, prev_close=1480.0)

    def daily_kline(self, code: str, start: date, end: date) -> pd.DataFrame:
        n = (end - start).days + 1
        return pd.DataFrame({
            "date": [(start + timedelta(days=i)).isoformat() for i in range(n)],
            "open": [10.0] * n, "high": [11.0] * n, "low": [9.5] * n,
            "close": [1000 + i for i in range(n)],
            "volume": [1e5] * n, "amount": [1e6] * n, "turnover_pct": [1.0] * n,
        })

    def valuation(self, code: str) -> Valuation:
        return Valuation(code=code, ts=datetime.utcnow(),
                         pe_ttm=25.0, pb=8.0, dv_ratio=1.5,
                         pe_pct_5y=40.0, pb_pct_5y=55.0)

    def financial_reports(self, code: str, kind: str, periods: int = 8) -> pd.DataFrame:
        return pd.DataFrame({
            "报告日": ["20260630", "20260331", "20251231", "20250930", "20250630"],
            "营业总收入": [1200, 600, 1000, 800, 600],
            "归属于母公司所有者的净利润": [300, 150, 250, 200, 150],
        })

    def financial_metrics(self, code: str, periods: int = 8):
        return [FinancialMetrics(code=code, period="20260630",
                                 roe=17.0, gross_margin=91.0, net_margin=50.0,
                                 debt_ratio=15.0, ocf_to_revenue=0.77,
                                 revenue_yoy_pct=1.3, net_profit_yoy_pct=-2.0,
                                 eps=35.5, bvps=200.0)]

    def index_daily(self, index_code: str, start: date, end: date) -> pd.DataFrame:
        n = (end - start).days + 1
        return pd.DataFrame({
            "date": [(start + timedelta(days=i)).isoformat() for i in range(n)],
            "open": [4000.0] * n, "high": [4100.0] * n, "low": [3900.0] * n,
            "close": [4000 + i * 0.5 for i in range(n)],
            "volume": [1e8] * n,
        })

    def announcements(self, code: str, since: date):
        return [Announcement(code=code, title="回购公告", url="",
                             publish_time=datetime.now(), kind="回购")]

    def news(self, code: str, since: date, limit: int = 50):
        return [NewsItem(code=code, title="行业景气回升", url="",
                         publish_time=datetime.now(), source="新华社")]

    def margin_snapshot(self, code: str):
        return MarginSnapshot(code=code, date="20260828",
                              margin_balance=1.7e10, margin_buy=1.6e8,
                              short_balance=None, short_sell_volume=3000.0)

    def shareholder_count(self, code: str):
        return ShareholderSnapshot(code=code, period="2026-06-30",
                                   count=296404, count_change_pct=21.9,
                                   holdings_per_account=5e6)

    def fund_holdings(self, code: str):
        return FundHoldingSummary(code=code, period="20260630",
                                  fund_count=1242, total_shares=4.16e7,
                                  holdings_value=4.94e10,
                                  change_direction="减仓", change_pct=-36.65)

    def research_reports(self, code: str, limit: int = 20):
        return []

    def consensus(self, code: str):
        return ResearchConsensus(
            code=code, report_count=30,
            ratings={"买入": 21, "增持": 6, "持有": 3},
            eps_next_year_median=71.95,
            eps_next_year_min=68.97, eps_next_year_max=76.93,
            pe_next_year_median=19.0,
        )


def _install_fake():
    registry._chains.clear()
    registry._providers.clear()
    registry._failed.clear()
    fake = FakeAll()
    for cap in ("meta", "quote", "fundamental", "metrics", "index",
                "disclosure", "news", "capital", "institution", "research"):
        registry._chains[cap] = [("fake", fake)]
    registry._providers["fake"] = fake


def test_study_dry_run_end_to_end(tmp_path):
    _install_fake()
    cfg = load()
    result = study(cfg, "600519")  # narrator=None → dry-run

    assert result.brief_path.exists()
    md = result.brief_path.read_text(encoding="utf-8")
    assert "# 贵州茅台 (600519)" in md
    assert "```json" in md

    assert result.advice.action == "watch"
    assert result.advice.confidence == 0.0
    assert "dry-run" in result.advice.rationale

    # 简报和建议已入库
    from ripple.models import Advice, Brief, session
    with session() as s:
        assert s.get(Brief, result.brief_id) is not None
        assert s.get(Advice, result.advice_id) is not None
