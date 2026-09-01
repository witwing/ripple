from ripple.analyze.narrative import BriefContext, render_dryrun_brief


def _sample_ctx() -> BriefContext:
    return BriefContext(
        ticker={"code": "600519", "name": "贵州茅台", "industry": "白酒"},
        profile={
            "code": "600519", "name": "贵州茅台",
            "price": 1500.0, "prev_close": 1480.0, "price_change_1d_pct": 1.35,
            "price_change_1m_pct": 2.5, "price_change_3m_pct": -3.0, "price_change_1y_pct": 8.0,
            "kline_range_pct_20d": 5.0,
            "pe_ttm": 25.0, "pb": 8.0, "dv_ratio": 1.5, "pe_pct_5y": 40.0, "pb_pct_5y": 55.0,
            "revenue_yoy_pct": 12.5, "net_profit_yoy_pct": 15.3,
        },
        recent_kline_summary="近 20 日振幅 5.0%",
        announcements=[{"date": "2026-08-15", "title": "关于回购的公告", "kind": "回购"}],
        news=[{"date": "2026-08-20", "title": "行业景气回升", "source": "新华社"}],
        recalled_notes=[{"id": "note_x", "excerpt": "渠道调研...", "score": 0.31,
                         "tickers": ["600519"], "tags": ["白酒"]}],
        user_stance="- note_x: 渠道调研…",
        signals=[{"label": "估值", "light": "🟢", "note": "PE 处 5Y 40% 分位"},
                 {"label": "成长", "light": "🟢", "note": "营收同比 +12.5%"}],
        scores=[{"dim": "估值", "score": 3, "basis": "PE 5Y 分位 40%"},
                {"dim": "成长", "score": 2, "basis": "营收同比 +12.5%"}],
    )


def test_dryrun_brief_shape():
    md = render_dryrun_brief(_sample_ctx())
    # 美化版结构
    assert "# 贵州茅台 (600519)" in md
    assert "## 📊 信号面板" in md
    assert "## 一、关键指标" in md
    assert "## 六、投资价值评分" in md
    assert "## 七、短/中/长期洞察" in md
    assert "## 八、结论" in md
    # JSON 结论块存在
    assert "```json" in md
    assert '"action": "watch"' in md
    # 事实字段被渲染
    assert "1500" in md
