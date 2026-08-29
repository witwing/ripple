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
    # 模拟 sina 宽表：项目 | 最近期 | 上一期 | ... | 4 期前（=去年同期）
    df = pd.DataFrame({
        "项目": ["营业总收入", "归属于母公司股东的净利润"],
        "2026-06-30": ["1200", "300"],
        "2026-03-31": ["600", "150"],
        "2025-12-31": ["1000", "250"],
        "2025-09-30": ["800", "200"],
    })
    p = build_profile("600519", None, quote=None, kline=None, valuation=None, income=df)
    # 最近期 1200 vs 下一个可用 600 → +100%（本测试仅验证解析逻辑跑通）
    assert p.revenue_yoy_pct is not None
    assert p.net_profit_yoy_pct is not None
