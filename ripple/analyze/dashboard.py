"""把 Profile 变成可视化元素：信号灯 / 分位条 / 维度打分。

这些都是**规则计算**（不调 LLM），保证可复现、可解释。
LLM 只负责"洞察"与"价值分析"的文字，数据可视化由这里生成。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from ripple.analyze.profile import Profile


def _valuation_percentile_unreliable(p: Profile) -> bool:
    """判断 PE/PB 的 5Y 分位是否不可信：上市不足 3 年样本不足。"""
    if not p.list_date:
        return False
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            d = datetime.strptime(p.list_date, fmt).date()
            break
        except ValueError:
            continue
    else:
        return False
    days_listed = (date.today() - d).days
    return days_listed < 365 * 3


# ---- 信号灯 ----

GREEN = "🟢"
YELLOW = "🟡"
RED = "🔴"
GREY = "⚪"


@dataclass
class Signal:
    label: str
    light: str
    note: str


def _light_by_threshold(value: float | None, good_below=None, bad_above=None,
                        good_above=None, bad_below=None) -> str:
    """按阈值给灯色。支持"越低越好"和"越高越好"两种。"""
    if value is None:
        return GREY
    # 越低越好（如估值分位）
    if good_below is not None and bad_above is not None:
        if value <= good_below:
            return GREEN
        if value >= bad_above:
            return RED
        return YELLOW
    # 越高越好（如 ROE / 现金流比）
    if good_above is not None and bad_below is not None:
        if value >= good_above:
            return GREEN
        if value <= bad_below:
            return RED
        return YELLOW
    return GREY


def build_signals(p: Profile) -> list[Signal]:
    """从 profile 生成一组信号灯。"""
    signals: list[Signal] = []

    # 估值信号
    unreliable = _valuation_percentile_unreliable(p)
    if p.pe_ttm is not None and p.pe_ttm > 100:
        # 绝对高估值：分位再低也不算便宜，强制红灯
        signals.append(Signal(
            "估值", RED,
            f"PE {p.pe_ttm:.0f}x 绝对高估" + ("（次新，分位不可信）" if unreliable else ""),
        ))
    elif p.pe_ttm is not None and p.pe_ttm < 0:
        # 亏损无 PE
        signals.append(Signal("估值", RED, f"PE {p.pe_ttm:.0f}x（亏损）"))
    elif unreliable and p.pe_ttm is not None:
        # 次新股：5Y 分位样本不足，标黄提示
        signals.append(Signal(
            "估值", YELLOW,
            f"PE {p.pe_ttm:.0f}x（次新，5Y 分位不可信）",
        ))
    elif p.pe_pct_5y is not None:
        signals.append(Signal(
            "估值", _light_by_threshold(p.pe_pct_5y, good_below=30, bad_above=70),
            f"PE 处 5Y {p.pe_pct_5y:.0f}% 分位",
        ))

    # 成长（营收同比，越高越好）
    if p.revenue_yoy_pct is not None:
        signals.append(Signal(
            "成长", _light_by_threshold(p.revenue_yoy_pct, good_above=15, bad_below=0),
            f"营收同比 {p.revenue_yoy_pct:+.1f}%",
        ))

    # 盈利质量（净利同比，越高越好）
    if p.net_profit_yoy_pct is not None:
        signals.append(Signal(
            "盈利", _light_by_threshold(p.net_profit_yoy_pct, good_above=10, bad_below=0),
            f"净利同比 {p.net_profit_yoy_pct:+.1f}%",
        ))

    # 现金流（经营现金流/营收，越高越好）
    if p.ocf_to_revenue is not None:
        signals.append(Signal(
            "现金流", _light_by_threshold(p.ocf_to_revenue, good_above=0.15, bad_below=0),
            f"经营现金流/营收 {p.ocf_to_revenue:.2f}",
        ))

    # ROE（越高越好）
    if p.roe is not None:
        signals.append(Signal(
            "回报", _light_by_threshold(p.roe, good_above=15, bad_below=5),
            f"ROE {p.roe:.1f}%",
        ))

    # 资金/筹码（公募加减仓 + 股东户数）
    if p.fund_change_pct is not None:
        # 公募增仓好，减仓差
        signals.append(Signal(
            "机构", _light_by_threshold(p.fund_change_pct, good_above=10, bad_below=-10),
            f"公募{p.fund_change_direction or ''} {p.fund_change_pct:+.1f}%",
        ))

    # 相对大盘（近 3 月 vs 沪深300）
    if p.price_vs_hs300_3m_pp is not None:
        signals.append(Signal(
            "相对强弱", _light_by_threshold(p.price_vs_hs300_3m_pp, good_above=5, bad_below=-5),
            f"近3月 vs 沪深300 {p.price_vs_hs300_3m_pp:+.1f}pp",
        ))

    return signals


def signal_bar(signals: list[Signal]) -> str:
    """一行信号灯总览。"""
    return "  ".join(f"{s.light}{s.label}" for s in signals)


# ---- 分位条形图 ----

def pct_bar(pct: float | None, width: int = 10) -> str:
    """把 0-100 的分位画成 ██████░░░░ 形式。"""
    if pct is None:
        return "─" * width + " (缺)"
    pct = max(0.0, min(100.0, pct))
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled) + f" {pct:.0f}%"


# ---- 维度打分 ----

@dataclass
class DimScore:
    dim: str
    score: int          # 0-5
    basis: str          # 打分依据


def _clip5(x: float) -> int:
    return int(max(0, min(5, round(x))))


def build_scores(p: Profile) -> list[DimScore]:
    """四维打分（0-5），纯规则。给 LLM 和用户一个量化锚点。"""
    scores: list[DimScore] = []

    # 估值（分位越低分越高；但绝对高估值 / 次新分位不可信要压分）
    if p.pe_ttm is not None and p.pe_ttm > 100:
        scores.append(DimScore("估值", _clip5(1), f"PE {p.pe_ttm:.0f}x 绝对高估"))
    elif p.pe_ttm is not None and p.pe_ttm < 0:
        scores.append(DimScore("估值", 0, f"PE {p.pe_ttm:.0f}x（亏损）"))
    elif _valuation_percentile_unreliable(p) and p.pe_ttm is not None:
        # 次新股分位不可信，给中性 2 分并注明
        scores.append(DimScore("估值", 2, f"PE {p.pe_ttm:.0f}x（次新，分位不可信）"))
    elif p.pe_pct_5y is not None:
        s = _clip5(5 - p.pe_pct_5y / 20)  # 0%→5, 100%→0
        scores.append(DimScore("估值", s, f"PE 5Y 分位 {p.pe_pct_5y:.0f}%"))

    # 成长（营收同比）
    if p.revenue_yoy_pct is not None:
        s = _clip5(p.revenue_yoy_pct / 10)  # 50%→5
        scores.append(DimScore("成长", s, f"营收同比 {p.revenue_yoy_pct:+.1f}%"))

    # 质量（ROE + 现金流综合）
    if p.roe is not None:
        base = p.roe / 5  # 25%→5
        if p.ocf_to_revenue is not None and p.ocf_to_revenue < 0:
            base -= 1.5  # 现金流为负扣分
        scores.append(DimScore("质量", _clip5(base),
                               f"ROE {p.roe:.1f}%"
                               + (f"，现金流/营收 {p.ocf_to_revenue:.2f}" if p.ocf_to_revenue is not None else "")))

    # 资金（公募加减仓）
    if p.fund_change_pct is not None:
        s = _clip5(2.5 + p.fund_change_pct / 40)  # +100%→5, -100%→0
        scores.append(DimScore("资金", s, f"公募{p.fund_change_direction or ''} {p.fund_change_pct:+.1f}%"))

    return scores


def score_stars(score: int) -> str:
    return "★" * score + "☆" * (5 - score)
