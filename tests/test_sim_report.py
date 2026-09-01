from ripple.simulate import ledger, report


def _fixed_price(_code):
    return 1400.0


def test_report_marks_to_market(tmp_path):
    ledger.get_or_create_portfolio(cash=1_000_000.0)
    ledger.buy("600519", 100, 1300.0)
    rep = report.build_report(price_lookup=_fixed_price)
    assert rep is not None
    assert len(rep.holdings) == 1
    h = rep.holdings[0]
    assert h.last_price == 1400.0
    # 现价 1400 > 成本 → 浮盈为正
    assert h.unrealized_pnl > 0
    # 净值 = 现金 + 持仓市值
    assert abs(rep.nav - (rep.cash + rep.holdings_value)) < 1e-6
    # 有初始现金 → 有总收益率
    assert rep.total_return_pct is not None


def test_report_none_when_no_portfolio(tmp_path):
    assert report.build_report(pid="nonexistent", price_lookup=_fixed_price) is None


def test_snapshot_and_series(tmp_path):
    ledger.get_or_create_portfolio(cash=1_000_000.0)
    ledger.buy("600519", 100, 1300.0)
    np = report.snapshot_nav(price_lookup=_fixed_price)
    assert np is not None
    series = report.nav_series()
    assert len(series) == 1
    assert series[0].nav == np.nav


def test_realized_flows_into_report(tmp_path):
    ledger.get_or_create_portfolio(cash=1_000_000.0)
    ledger.buy("600519", 100, 1300.0)
    ledger.sell("600519", 100, 1500.0)
    rep = report.build_report(price_lookup=_fixed_price)
    assert rep.realized_pnl_total > 0
    assert rep.holdings == []
