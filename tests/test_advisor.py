from ripple.analyze.advisor import parse_from_brief


LIVE = """# 贵州茅台 简报

## 五、结论

```json
{
  "action": "buy",
  "size_pct": 5,
  "confidence": 0.72,
  "horizon_days": 60,
  "rationale": "估值分位低 + 现金流稳定",
  "horizon_views": {"short": "中性", "mid": "看多", "long": "看多"},
  "value_scores": {"valuation": 4, "growth": 2, "quality": 5, "capital": 3}
}
```
"""

MALFORMED = """# ...

## 五、结论

```json
{ this is not json
```
"""

MISSING = """# 无结论段落
一些文本
"""

OUT_OF_RANGE = """# ...

## 五、结论

```json
{"action":"whatever","size_pct":200,"confidence":5,"horizon_days":"abc","rationale":""}
```
"""


def test_parse_live():
    a = parse_from_brief(LIVE)
    assert a.action == "buy"
    assert a.size_pct == 5
    assert a.confidence == 0.72
    assert a.horizon_days == 60
    assert "估值分位低" in a.rationale
    # 新增字段
    assert a.horizon_views == {"short": "中性", "mid": "看多", "long": "看多"}
    assert a.value_scores == {"valuation": 4, "growth": 2, "quality": 5, "capital": 3}


def test_parse_without_optional_fields():
    md = """## 结论
```json
{"action":"hold","size_pct":10,"confidence":0.5,"horizon_days":30,"rationale":"x"}
```"""
    a = parse_from_brief(md)
    assert a.action == "hold"
    assert a.horizon_views is None
    assert a.value_scores is None


def test_parse_malformed_falls_back():
    a = parse_from_brief(MALFORMED)
    assert a.action == "watch"
    assert a.confidence == 0.0
    assert "JSON" in a.rationale


def test_parse_missing_falls_back():
    a = parse_from_brief(MISSING)
    assert a.action == "watch"


def test_parse_clamps_and_defaults():
    a = parse_from_brief(OUT_OF_RANGE)
    assert a.action == "watch"  # invalid action → watch
    assert a.size_pct == 100    # clamped
    assert a.confidence == 1.0  # clamped
    assert a.horizon_days == 30  # default when unparseable
