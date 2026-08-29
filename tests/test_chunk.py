from ripple.notes.chunk import approx_tokens, chunk


def test_short_returns_single():
    body = "今天调研 600519，渠道偏弱。"
    assert chunk(body, max_tokens=400) == [body]


def test_long_splits_by_paragraph():
    para = "段落" * 300
    body = f"{para}\n\n{para}\n\n{para}"
    chunks = chunk(body, max_tokens=100)
    assert len(chunks) >= 2
    for c in chunks:
        # 每 chunk 不严格 <= max_tokens（单段超限也放进去），但至少要分裂
        assert c.strip()


def test_approx_tokens_smoke():
    assert approx_tokens("中文") == 2
    assert approx_tokens("abcdefg") == int(7 / 3.5)
