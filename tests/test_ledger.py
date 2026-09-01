import pytest

from ripple.simulate import ledger
from ripple.simulate.fees import compute_fees


def test_fees_buy_min_commission():
    # 小额买入触发最低佣金 5 元
    f = compute_fees(price=10.0, qty=100, side="buy")
    assert f.commission == 5.0        # 1000 * 0.00025 = 0.25 → 提到 5
    assert f.stamp_tax == 0.0         # 买入不收印花税
    assert f.transfer_fee == 0.01     # 1000 * 0.00001


def test_fees_sell_has_stamp():
    f = compute_fees(price=100.0, qty=1000, side="sell")
    turnover = 100_000
    assert f.commission == round(turnover * 0.00025, 2)  # 25
    assert f.stamp_tax == round(turnover * 0.0005, 2)    # 50
    assert f.transfer_fee == round(turnover * 0.00001, 2)  # 1


def test_buy_then_position_and_cash(tmp_path):
    ledger.get_or_create_portfolio(cash=1_000_000.0)
    r = ledger.buy("600519", 100, 1300.0)
    # 成本 = 130000 + 费
    assert r.qty_after == 100
    assert r.avg_cost_after > 1300.0   # 费摊进成本
    assert r.cash_after < 1_000_000.0
    pos = ledger.positions()
    assert len(pos) == 1
    assert pos[0].code == "600519" and pos[0].qty == 100


def test_buy_non_lot_rejected(tmp_path):
    ledger.get_or_create_portfolio()
    with pytest.raises(ledger.TradeError):
        ledger.buy("600519", 150, 1300.0)


def test_insufficient_cash(tmp_path):
    ledger.get_or_create_portfolio(cash=1000.0)
    with pytest.raises(ledger.TradeError):
        ledger.buy("600519", 100, 1300.0)


def test_sell_more_than_held(tmp_path):
    ledger.get_or_create_portfolio()
    ledger.buy("600519", 100, 1300.0)
    with pytest.raises(ledger.TradeError):
        ledger.sell("600519", 200, 1350.0)


def test_realized_pnl_positive(tmp_path):
    ledger.get_or_create_portfolio(cash=1_000_000.0)
    b = ledger.buy("600519", 100, 1300.0)
    # 以更高价卖出应为正已实现（扣双边费用后）
    s = ledger.sell("600519", 100, 1400.0)
    assert s.realized_pnl is not None
    # 毛利 100*100=10000，减去买卖费用后仍应为正
    assert s.realized_pnl > 9000
    # 清仓后无持仓
    assert ledger.positions() == []


def test_weighted_avg_cost(tmp_path):
    ledger.get_or_create_portfolio(cash=1_000_000.0)
    ledger.buy("600519", 100, 1000.0)
    r = ledger.buy("600519", 100, 1200.0)
    # 均价应在 1000-1200 之间且略高于 1100（含费）
    assert 1100 < r.avg_cost_after < 1120
    assert r.qty_after == 200


def test_advice_linkage(tmp_path):
    ledger.get_or_create_portfolio()
    ledger.buy("600519", 100, 1300.0, advice_id="adv_test_001")
    ts = ledger.trades()
    assert ts[-1].advice_id == "adv_test_001"
