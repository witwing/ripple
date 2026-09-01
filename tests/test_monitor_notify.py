from ripple.monitor.notify import build_digest_text
from ripple.monitor.rules import Trigger
from ripple.monitor.scan import ScanHit, ScanResult


def _hit(code, name, action, conf, triggers):
    return ScanHit(code=code, name=name, action=action, confidence=conf,
                   triggers=triggers, chart_path=None, digest="")


def test_digest_empty():
    txt = build_digest_text(ScanResult(scanned=5, hits=[]))
    assert "暂无触发" in txt
    assert "5" in txt


def test_digest_strong_and_normal():
    res = ScanResult(scanned=3)
    res.hits = [
        _hit("600519", "贵州茅台", "buy", 0.72,
             [Trigger("action_upgrade", "结论升级：watch → buy（置信度 72%）", strong=True)]),
        _hit("000858", "五粮液", "watch", 0.5,
             [Trigger("valuation_low", "估值到位：PE 处 5Y 15% 低分位", strong=False)]),
    ]
    txt = build_digest_text(res)
    assert "强信号" in txt
    assert "贵州茅台" in txt and "买入" in txt
    assert "值得关注" in txt
    assert "五粮液" in txt and "估值到位" in txt


def test_digest_only_normal_no_strong_header():
    res = ScanResult(scanned=1)
    res.hits = [_hit("000858", "五粮液", "watch", 0.5,
                     [Trigger("valuation_low", "估值到位", strong=False)])]
    txt = build_digest_text(res)
    assert "强信号" not in txt
    assert "值得关注" in txt
