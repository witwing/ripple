"""Web API 测试：用 FastAPI TestClient，不起真服务器；分析走 dry-run。"""
from __future__ import annotations

import pandas as pd
import pytest

from ripple.providers.base import (
    Announcement, FinancialMetrics, FundHoldingSummary, HealthStatus,
    MarginSnapshot, NewsItem, Quote, ResearchConsensus, ShareholderSnapshot,
    TickerProfile, Valuation,
)
from ripple.providers.registry import registry


class FakeAll:
    name = "fake"
    def health(self): return HealthStatus(provider="fake", ok=True, latency_ms=1)
    def profile(self, code): return TickerProfile(code=code, name="测试股", industry="白酒",
                                                  exchange="SH", board="MAIN", list_date="2001-01-01")
    def snapshot(self, code): return Quote(code=code, ts=__import__("datetime").datetime.utcnow(),
                                           price=100.0, prev_close=99.0)
    def daily_kline(self, code, start, end):
        n=(end-start).days+1
        return pd.DataFrame({"date":[(start+pd.Timedelta(days=i)).isoformat() for i in range(n)],
            "open":[10.]*n,"high":[11.]*n,"low":[9.]*n,"close":[100+i*0.01 for i in range(n)],
            "volume":[1e5]*n,"amount":[1e6]*n,"turnover_pct":[1.]*n})
    def valuation(self, code): return Valuation(code=code, ts=__import__("datetime").datetime.utcnow(),
                                                pe_ttm=20.,pb=3.,pe_pct_5y=30.,pb_pct_5y=25.)
    def financial_reports(self, code, kind, periods=8): return pd.DataFrame()
    def financial_metrics(self, code, periods=8):
        return [FinancialMetrics(code=code, period="20260630", roe=15., gross_margin=50.,
                net_margin=30., debt_ratio=20., ocf_to_revenue=0.5, revenue_yoy_pct=10.,
                net_profit_yoy_pct=8., eps=2., bvps=13.)]
    def index_daily(self, idx, start, end):
        n=(end-start).days+1
        return pd.DataFrame({"date":[(start+pd.Timedelta(days=i)).isoformat() for i in range(n)],
            "open":[4000.]*n,"high":[4100.]*n,"low":[3900.]*n,"close":[4000+i*0.5 for i in range(n)],"volume":[1e8]*n})
    def announcements(self, code, since): return []
    def news(self, code, since, limit=50): return []
    def margin_snapshot(self, code): return None
    def shareholder_count(self, code): return None
    def fund_holdings(self, code): return None
    def consensus(self, code): return ResearchConsensus(code=code)


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient
    from ripple.web.app import create_app
    # 装 fake provider
    registry._chains.clear(); registry._providers.clear(); registry._failed.clear()
    fake = FakeAll()
    for cap in ("meta","quote","fundamental","metrics","index","disclosure",
                "news","capital","institution","research"):
        registry._chains[cap] = [("fake", fake)]
    registry._providers["fake"] = fake
    return TestClient(create_app())


def test_watch_add_list_remove(client):
    assert client.post("/api/watch/600519").json()["ok"] is True
    codes = [w["code"] for w in client.get("/api/watch").json()]
    assert "600519" in codes
    client.delete("/api/watch/600519")
    assert "600519" not in [w["code"] for w in client.get("/api/watch").json()]


def test_watch_bad_code(client):
    assert client.post("/api/watch/12345").status_code == 400


def test_study_job_flow(client):
    import time
    r = client.post("/api/study/600519?no_llm=true")
    job_id = r.json()["job_id"]
    for _ in range(50):
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.2)
    assert j["status"] == "done"
    assert j["result"]["code"] == "600519"


def test_portfolio_init_and_status(client):
    client.post("/api/portfolio/init?cash=500000")
    pf = client.get("/api/portfolio").json()
    assert pf["cash"] == 500000
    # 买入
    r = client.post("/api/portfolio/buy?code=600519&qty=100&price=100")
    assert r.status_code == 200
    pf2 = client.get("/api/portfolio").json()
    assert len(pf2["holdings"]) == 1


def test_pages_render(client):
    assert client.get("/").status_code == 200
    assert client.get("/portfolio").status_code == 200
    assert client.get("/monitor").status_code == 200
    assert client.get("/stock/600519").status_code == 200
