from datetime import date, timedelta

from ripple.analyze.dashboard import build_scores, build_signals
from ripple.analyze.profile import Profile


def _sig(signals, label):
    for s in signals:
        if s.label == label:
            return s
    return None


def test_high_absolute_pe_forces_red():
    # PE 391 但分位显示 11%（次新失真）→ 强制红灯
    p = Profile(code="688836", name="宇树科技", pe_ttm=391.0, pe_pct_5y=11.0,
                list_date=(date.today() - timedelta(days=200)).isoformat())
    sig = _sig(build_signals(p), "估值")
    assert sig is not None
    assert sig.light == "🔴"
    assert "绝对高估" in sig.note


def test_newly_listed_percentile_yellow():
    # 上市不足 3 年、PE 不算极端 → 黄灯提示分位不可信
    p = Profile(code="301999", name="次新", pe_ttm=45.0, pe_pct_5y=8.0,
                list_date=(date.today() - timedelta(days=300)).isoformat())
    sig = _sig(build_signals(p), "估值")
    assert sig.light == "🟡"
    assert "不可信" in sig.note


def test_mature_low_percentile_green():
    # 老股 + 低分位 → 正常绿灯
    p = Profile(code="600519", name="贵州茅台", pe_ttm=20.0, pe_pct_5y=11.0,
                list_date="2001-08-27")
    sig = _sig(build_signals(p), "估值")
    assert sig.light == "🟢"
    assert "5Y" in sig.note


def test_negative_pe_red():
    p = Profile(code="600000", pe_ttm=-15.0, list_date="2000-01-01")
    sig = _sig(build_signals(p), "估值")
    assert sig.light == "🔴"
    assert "亏损" in sig.note


def test_score_high_pe_compressed():
    p = Profile(code="688836", pe_ttm=391.0, pe_pct_5y=11.0,
                list_date=(date.today() - timedelta(days=200)).isoformat())
    scores = {d.dim: d for d in build_scores(p)}
    assert scores["估值"].score <= 1   # 高估值不该给高分
