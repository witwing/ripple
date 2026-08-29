import pytest

from ripple.core.symbol import Symbol


@pytest.mark.parametrize("code, exch, board", [
    ("600519", "SH", "MAIN"),
    ("688981", "SH", "STAR"),
    ("000001", "SZ", "MAIN"),
    ("002415", "SZ", "MAIN"),
    ("300750", "SZ", "CHINEXT"),
    ("301021", "SZ", "CHINEXT"),
    ("830799", "BJ", "BSE"),
    ("sh600519", "SH", "MAIN"),
    ("600519.SH", "SH", "MAIN"),
])
def test_parse_ok(code, exch, board):
    s = Symbol.parse(code)
    assert s.code[-6:].isdigit()
    assert s.exchange == exch
    assert s.board == board


@pytest.mark.parametrize("code", ["12345", "abcdef", "700000", "500000"])
def test_parse_reject(code):
    with pytest.raises(ValueError):
        Symbol.parse(code)


def test_to_vendor_format():
    s = Symbol.parse("600519")
    assert s.to_akshare() == "sh600519"
    assert s.to_tushare() == "600519.SH"
