"""study 编排端到端测试：用假 provider，验证整个链路和 dry-run 渲染。"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from ripple.analyze.study import study
from ripple.core.config import load
from ripple.providers.base import (
    Announcement,
    HealthStatus,
    NewsItem,
    Quote,
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
                             exchange="SH", board="MAIN", list_date="2001-08-27")

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
            "项目": ["营业总收入", "归属于母公司股东的净利润"],
            "2026-06-30": ["1200", "300"],
            "2025-06-30": ["1000", "250"],
        })

    def announcements(self, code: str, since: date):
        return [Announcement(code=code, title="回购公告", url="",
                             publish_time=datetime.now(), kind="回购")]

    def news(self, code: str, since: date, limit: int = 50):
        return [NewsItem(code=code, title="行业景气回升", url="",
                         publish_time=datetime.now(), source="新华社")]


def _install_fake():
    registry._chains.clear()
    registry._providers.clear()
    registry._failed.clear()
    fake = FakeAll()
    for cap in ("meta", "quote", "fundamental", "disclosure", "news"):
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
