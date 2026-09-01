"""universe 同步/搜索测试：用 fake akshare 模块，不打网络。"""
from __future__ import annotations

import pandas as pd

from ripple.data import universe


class FakeAk:
    def stock_info_sh_name_code(self, symbol="主板A股"):
        if symbol == "主板A股":
            return pd.DataFrame({
                "证券代码": ["600519", "600000"],
                "证券简称": ["贵州茅台", "浦发银行"],
                "上市日期": ["2001-08-27", "1999-11-10"],
            })
        else:  # 科创板
            return pd.DataFrame({
                "证券代码": ["688775"],
                "证券简称": ["影石创新"],
                "上市日期": ["2020-01-01"],
            })

    def stock_info_sz_name_code(self, symbol="A股列表"):
        return pd.DataFrame({
            "板块": ["主板", "创业板"],
            "A股代码": ["000858", "300750"],
            "A股简称": ["五粮液", "宁德时代"],
            "A股上市日期": ["1998-04-27", "2018-06-11"],
            "所属行业": ["C 制造业", "C 制造业"],
        })

    def stock_info_bj_name_code(self):
        raise RuntimeError("bj unavailable")


def test_sync_populates(tmp_path):
    n, notes = universe.sync(ak_module=FakeAk())
    assert n == 5  # 2 sh主板 + 1 科创 + 2 深
    assert universe.count() == 5
    # 北交所失败被记录但不阻断
    assert any("北交所" in x for x in notes)


def test_search_by_code_prefix(tmp_path):
    universe.sync(ak_module=FakeAk())
    rows = universe.search("6005")
    codes = {r.code for r in rows}
    assert "600519" in codes   # 600519 命中前缀 6005
    rows2 = universe.search("600")
    assert {"600519", "600000"} <= {r.code for r in rows2}


def test_search_by_name(tmp_path):
    universe.sync(ak_module=FakeAk())
    rows = universe.search("茅台")
    assert len(rows) == 1
    assert rows[0].code == "600519"


def test_search_by_pinyin(tmp_path):
    universe.sync(ak_module=FakeAk())
    rows = universe.search("wly")   # 五粮液
    codes = {r.code for r in rows}
    # pypinyin 装了才有拼音；装了就该命中
    from importlib.util import find_spec
    if find_spec("pypinyin"):
        assert "000858" in codes


def test_board_mapping(tmp_path):
    universe.sync(ak_module=FakeAk())
    assert universe.get("688775").board == "STAR"
    assert universe.get("300750").board == "CHINEXT"
    assert universe.get("600519").board == "MAIN"
    assert universe.get("688775").exchange == "SH"
    assert universe.get("300750").exchange == "SZ"
