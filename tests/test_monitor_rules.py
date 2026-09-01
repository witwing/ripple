from ripple.analyze.advisor import ParsedAdvice
from ripple.analyze.profile import Profile
from ripple.monitor.rules import RuleConfig, evaluate


def _adv(action="watch", conf=0.5):
    return ParsedAdvice(action=action, size_pct=0, confidence=conf,
                        horizon_days=30, rationale="x")


RC = RuleConfig()


def test_valuation_low_triggers():
    p = Profile(code="600519", pe_ttm=18.0, pe_pct_5y=11.0, list_date="2001-08-27")
    ts = evaluate(p, _adv(), prev_action="watch", rc=RC)
    assert any(t.rule == "valuation_low" for t in ts)


def test_valuation_not_low_no_trigger():
    p = Profile(code="600519", pe_ttm=30.0, pe_pct_5y=60.0, list_date="2001-08-27")
    ts = evaluate(p, _adv(), prev_action="watch", rc=RC)
    assert not any(t.rule == "valuation_low" for t in ts)


def test_valuation_high_pe_skipped():
    # PE 391 分位显示 11% 但绝对高估 → 不该触发"估值到位"
    p = Profile(code="688836", pe_ttm=391.0, pe_pct_5y=11.0, list_date="2001-01-01")
    ts = evaluate(p, _adv(), prev_action="watch", rc=RC)
    assert not any(t.rule == "valuation_low" for t in ts)


def test_newly_listed_valuation_skipped():
    from datetime import date, timedelta
    p = Profile(code="301999", pe_ttm=40.0, pe_pct_5y=8.0,
                list_date=(date.today() - timedelta(days=200)).isoformat())
    ts = evaluate(p, _adv(), prev_action="watch", rc=RC)
    assert not any(t.rule == "valuation_low" for t in ts)


def test_action_upgrade_triggers():
    p = Profile(code="600519", pe_ttm=30.0, pe_pct_5y=60.0, list_date="2001-08-27")
    ts = evaluate(p, _adv("buy", 0.7), prev_action="watch", rc=RC)
    up = [t for t in ts if t.rule == "action_upgrade"]
    assert up and up[0].strong is True   # buy + 高置信 = 强信号


def test_action_upgrade_hold_not_strong():
    p = Profile(code="600519", pe_ttm=30.0, pe_pct_5y=60.0, list_date="2001-08-27")
    ts = evaluate(p, _adv("hold", 0.7), prev_action="watch", rc=RC)
    up = [t for t in ts if t.rule == "action_upgrade"]
    assert up and up[0].strong is False  # 升到 hold 不算强


def test_action_downgrade_no_trigger():
    p = Profile(code="600519", pe_ttm=30.0, pe_pct_5y=60.0, list_date="2001-08-27")
    ts = evaluate(p, _adv("watch", 0.7), prev_action="buy", rc=RC)
    assert not any(t.rule == "action_upgrade" for t in ts)


def test_no_prev_action_no_upgrade():
    p = Profile(code="600519", pe_ttm=30.0, pe_pct_5y=60.0, list_date="2001-08-27")
    ts = evaluate(p, _adv("buy", 0.9), prev_action=None, rc=RC)
    assert not any(t.rule == "action_upgrade" for t in ts)
