from datetime import date, datetime, timedelta

import pandas as pd

from ripple.analyze.profile import build_profile
from ripple.providers.base import Quote, Valuation


def _fake_kline(n_days: int = 400) -> pd.DataFrame:
    dates = [date.today() - timedelta(days=i) for i in range(n_days)][::-1]
    return pd.DataFrame({
        "date": [d.isoformat() for d in dates],
        "open": [10.0] * n_days,
        "high": [11.0] * n_days,
        "low": [9.5] * n_days,
        "close": [10.0 + 0.01 * i for i in range(n_days)],
        "volume": [1e5] * n_days,
        "amount": [1e6] * n_days,
        "turnover_pct": [1.0] * n_days,
    })


def test_profile_from_quote_only():
    q = Quote(code="600519", ts=datetime.utcnow(), price=101.0, prev_close=100.0)
    p = build_profile("600519", "贵州茅台", quote=q, kline=None, valuation=None, income=None)
    assert p.price == 101.0
    assert p.price_change_1d_pct == 1.0
    assert p.pe_ttm is None
    assert p.revenue_yoy_pct is None


def test_profile_price_changes_from_kline():
    kline = _fake_kline(400)
    p = build_profile("600519", None, quote=None, kline=kline, valuation=None, income=None)
    assert p.price_change_1m_pct is not None
    assert p.price_change_1y_pct is not None
    # 单调递增的 close，应为正
    assert p.price_change_1y_pct > 0


def test_profile_valuation_passthrough():
    v = Valuation(code="600519", ts=datetime.utcnow(), pe_ttm=25.0, pb=8.0, dv_ratio=1.5,
                  pe_pct_5y=45.0, pb_pct_5y=60.0)
    p = build_profile("600519", None, quote=None, kline=None, valuation=v, income=None)
    assert p.pe_ttm == 25.0
    assert p.pe_pct_5y == 45.0


def test_profile_income_yoy():
    # 模拟 sina 宽表结构：行=报告期，列=项目
    df = pd.DataFrame({
        "报告日": ["20260630", "20260331", "20251231", "20250930", "20250630"],
        "营业总收入": [1200, 600, 1000, 800, 600],
        "归属于母公司所有者的净利润": [300, 150, 250, 200, 150],
    })
    p = build_profile("600519", None, quote=None, kline=None, valuation=None, income=df)
    # 最近期 1200 vs 4 期前 600 → +100%
    assert p.revenue_yoy_pct == 100.0
    assert p.net_profit_yoy_pct == 100.0
