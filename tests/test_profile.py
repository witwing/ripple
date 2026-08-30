from datetime import date, datetime, timedelta

import pandas as pd

from ripple.analyze.profile import build_profile
from ripple.providers.base import FinancialMetrics, Quote, Valuation


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


def _kwargs(**over):
    """默认 kwargs，可覆盖。"""
    base = dict(code="600519", name="贵州茅台", industry="白酒",
                quote=None, kline=None, valuation=None, income=None)
    base.update(over)
    return base


def test_profile_from_quote_only():
    q = Quote(code="600519", ts=datetime.utcnow(), price=101.0, prev_close=100.0)
    p = build_profile(**_kwargs(quote=q))
    assert p.price == 101.0
    assert p.price_change_1d_pct == 1.0
    assert p.pe_ttm is None
    assert p.revenue_yoy_pct is None


def test_profile_price_changes_from_kline():
    kline = _fake_kline(400)
    p = build_profile(**_kwargs(kline=kline))
    assert p.price_change_1m_pct is not None
    assert p.price_change_1y_pct is not None
    assert p.price_change_1y_pct > 0


def test_profile_valuation_passthrough():
    v = Valuation(code="600519", ts=datetime.utcnow(), pe_ttm=25.0, pb=8.0, dv_ratio=1.5,
                  pe_pct_5y=45.0, pb_pct_5y=60.0)
    p = build_profile(**_kwargs(valuation=v))
    assert p.pe_ttm == 25.0
    assert p.pe_pct_5y == 45.0


def test_profile_income_yoy_fallback():
    # income 是 fallback：只有当 metrics 缺失时才用它
    df = pd.DataFrame({
        "报告日": ["20260630", "20260331", "20251231", "20250930", "20250630"],
        "营业总收入": [1200, 600, 1000, 800, 600],
        "归属于母公司所有者的净利润": [300, 150, 250, 200, 150],
    })
    p = build_profile(**_kwargs(income=df))
    assert p.revenue_yoy_pct == 100.0
    assert p.net_profit_yoy_pct == 100.0


def test_profile_metrics_win_over_income():
    """metrics 优先于 income 表：拿到的 ROE / 毛利率 / 净利率 才是关键字段。"""
    metrics = [
        FinancialMetrics(code="600519", period="20260630",
                         roe=17.0, gross_margin=91.0, net_margin=50.0,
                         debt_ratio=15.0, ocf_to_revenue=0.77,
                         revenue_yoy_pct=1.3, net_profit_yoy_pct=-2.0,
                         eps=35.5, bvps=200.0),
        # 4 期前用来算 ROE 同比
        FinancialMetrics(code="600519", period="20250930", roe=None, net_margin=None),
        FinancialMetrics(code="600519", period="20250630", roe=None, net_margin=None),
        FinancialMetrics(code="600519", period="20250331", roe=None, net_margin=None),
        FinancialMetrics(code="600519", period="20250630",
                         roe=18.5, net_margin=52.0),
    ]
    p = build_profile(**_kwargs(metrics=metrics))
    assert p.roe == 17.0
    assert p.gross_margin == 91.0
    assert p.net_margin == 50.0
    assert p.debt_ratio == 15.0
    assert p.ocf_to_revenue == 0.77
    assert p.revenue_yoy_pct == 1.3
    assert p.roe_yoy_change_pp == round(17.0 - 18.5, 2)
    assert p.net_margin_yoy_change_pp == round(50.0 - 52.0, 2)


def test_profile_relative_index():
    """股票涨 10%，指数涨 5% → 相对 +5pp"""
    stk = _fake_kline(400)  # 单调递增，1y 大约 +40%
    idx = _fake_kline(400)
    # 让指数更慢
    idx["close"] = [10.0 + 0.005 * i for i in range(len(idx))]
    p = build_profile(**_kwargs(kline=stk, index_kline=idx))
    assert p.price_vs_hs300_1y_pp is not None
    assert p.price_vs_hs300_1y_pp > 0  # 股票强于指数
