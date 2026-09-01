"""把 Profile 渲染成一张"看得懂"的可视化仪表盘 PNG（matplotlib）。

设计目标：非专业用户也能看懂。每个面板都自带大白话说明和结论标注：
- 顶部一句话结论横幅（动作 + 一句话）
- 信号灯配图例（好/一般/当心）
- 分位条标"便宜←→贵"
- 评分写清每维度看什么
- 同行散点标"理想区=又便宜又能赚"
- 走势直接标"跑赢/跑输大盘 X%"
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from ripple.analyze.dashboard import build_scores, build_signals
from ripple.analyze.profile import PeerRow, Profile

# ---- 字体 ----
_FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]
for _fp in _FONT_PATHS:
    if Path(_fp).exists():
        fm.fontManager.addfont(_fp)
        plt.rcParams["font.family"] = fm.FontProperties(fname=_fp).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False

# ---- 配色（深色主题）----
BG = "#16181d"
CARD = "#1e2128"
INK = "#f2f3f5"
INK2 = "#9aa0aa"
INK3 = "#6b7280"
GRID = "#2c3038"
BLUE = "#3987e5"
GOOD = "#1faf6f"
WARN = "#e0a300"
CRIT = "#e05753"
GREY = "#6b7280"

_LIGHT_COLOR = {"🟢": GOOD, "🟡": WARN, "🔴": CRIT, "⚪": GREY}

# 每个维度一句"看什么"的大白话
_DIM_HINT = {
    "估值": "现在贵不贵",
    "成长": "还能不能长大",
    "质量": "赚钱扎不扎实",
    "资金": "机构在买还是卖",
}
_SIGNAL_HINT = {
    "估值": "贵不贵",
    "成长": "营收增速",
    "盈利": "利润增速",
    "现金流": "赚的是真钱吗",
    "回报": "股东回报",
    "机构": "公募动向",
    "相对强弱": "跑赢大盘吗",
}


def _fmt(v, suffix="", nd=2):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}{suffix}"
    return f"{v}{suffix}"


def render_dashboard(
    profile: Profile,
    peers: list[PeerRow],
    kline_dates=None,
    kline_closes=None,
    index_closes=None,
    out_path: str | Path = "dashboard.png",
    verdict: str | None = None,      # 一句话结论
    action_cn: str | None = None,    # 买入/持有/观望/卖出
) -> Path:
    signals = build_signals(profile)
    scores = build_scores(profile)

    fig = plt.figure(figsize=(11.5, 9.6), dpi=140)
    fig.patch.set_facecolor(BG)

    gs = fig.add_gridspec(
        4, 2, height_ratios=[0.62, 0.95, 1.45, 1.9],
        hspace=0.5, wspace=0.16,
        left=0.055, right=0.955, top=0.945, bottom=0.055,
    )

    _title(fig, profile, action_cn, verdict)
    _signal_row(fig.add_subplot(gs[1, :]), signals)
    _percentile_panel(fig.add_subplot(gs[2, 0]), profile)
    _score_panel(fig.add_subplot(gs[2, 1]), scores)
    _peer_panel(fig.add_subplot(gs[3, 0]), profile, peers)
    _trend_panel(fig.add_subplot(gs[3, 1]), kline_closes, index_closes, profile)

    out = Path(out_path)
    fig.savefig(out, facecolor=BG, bbox_inches="tight", pad_inches=0.22)
    plt.close(fig)
    return out


def _title(fig, p: Profile, action_cn, verdict):
    name = p.name or p.code
    price = _fmt(p.price)
    chg = p.price_change_1d_pct
    chg_color = GOOD if (chg or 0) >= 0 else CRIT
    chg_str = f"{chg:+.2f}%" if chg is not None else "—"

    fig.text(0.055, 0.985, f"{name}", fontsize=26, color=INK, weight="bold", va="top")
    fig.text(0.055, 0.945, f"{p.code}  ·  {p.industry or '—'}", fontsize=12,
             color=INK2, va="top")
    fig.text(0.955, 0.985, f"¥{price}", fontsize=26, color=INK, weight="bold",
             va="top", ha="right")
    fig.text(0.955, 0.945, f"今日 {chg_str}", fontsize=12.5, color=chg_color,
             va="top", ha="right")

    # 一句话结论横幅
    if action_cn or verdict:
        act_color = {"买入": GOOD, "增持": GOOD, "持有": WARN, "观望": INK2,
                     "减持": CRIT, "卖出": CRIT}.get(action_cn or "", INK2)
        y = 0.905
        if action_cn:
            fig.text(0.055, y, f"● {action_cn}", fontsize=14, color=act_color,
                     weight="bold", va="top")
        if verdict:
            fig.text(0.16 if action_cn else 0.055, y, verdict, fontsize=11.5,
                     color=INK2, va="top")


def _card(ax, title, hint=None):
    ax.set_facecolor(CARD)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks([]); ax.set_yticks([])
    ax.add_patch(FancyBboxPatch(
        (0, 0), 1, 1, transform=ax.transAxes,
        boxstyle="round,pad=0,rounding_size=0.03",
        facecolor=CARD, edgecolor="none", zorder=-1, clip_on=False,
    ))
    if title:
        ax.text(0.035, 0.95, title, transform=ax.transAxes, fontsize=13,
                color=INK, weight="bold", va="top")
    if hint:
        ax.text(0.965, 0.95, hint, transform=ax.transAxes, fontsize=9.5,
                color=INK3, va="top", ha="right")


def _signal_row(ax, signals):
    _card(ax, None)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    # 图例
    ax.text(0.035, 0.9, "健康信号灯", transform=ax.transAxes, fontsize=12.5,
            color=INK, weight="bold", va="top")
    # 用画的圆点做图例，避免 emoji 字体缺字
    lx = 0.60
    for dot_color, word, w in [(GOOD, "好", 0.09), (WARN, "一般", 0.12), (CRIT, "当心", 0.12)]:
        ax.scatter([lx], [0.865], s=90, color=dot_color, edgecolors="none",
                   transform=ax.transAxes, zorder=3)
        ax.text(lx + 0.022, 0.865, word, transform=ax.transAxes, fontsize=9.5,
                color=INK2, va="center")
        lx += w + 0.04
    if not signals:
        ax.text(0.5, 0.4, "无信号数据", transform=ax.transAxes, color=INK2,
                ha="center", va="center")
        return
    n = len(signals)
    for i, s in enumerate(signals):
        cx = (i + 0.5) / n
        color = _LIGHT_COLOR.get(s.light, GREY)
        ax.scatter([cx], [0.56], s=440, color=color, edgecolors="none",
                   transform=ax.transAxes, zorder=3)
        ax.text(cx, 0.30, s.label, transform=ax.transAxes, fontsize=12,
                color=INK, ha="center", va="center", weight="bold")
        hint = _SIGNAL_HINT.get(s.label, "")
        if hint:
            ax.text(cx, 0.15, hint, transform=ax.transAxes, fontsize=8,
                    color=INK3, ha="center", va="center")


def _percentile_panel(ax, p: Profile):
    _card(ax, "现在贵不贵", hint="看 5 年历史位置")
    y0 = 0.70
    for label, val, pct in [("PE 市盈率", p.pe_ttm, p.pe_pct_5y),
                            ("PB 市净率", p.pb, p.pb_pct_5y)]:
        _pct_bar(ax, y0, label, val, pct)
        y0 -= 0.30

    # 底部四个盈利能力大字
    extra = [("ROE", _fmt(p.roe, "%"), "股东回报"),
             ("毛利率", _fmt(p.gross_margin, "%"), "产品竞争力"),
             ("净利率", _fmt(p.net_margin, "%"), "最终赚钱"),
             ("负债率", _fmt(p.debt_ratio, "%"), "欠债多少")]
    xs = [0.05, 0.29, 0.53, 0.77]
    for (lab, v, desc), x in zip(extra, xs):
        ax.text(x, 0.15, v, transform=ax.transAxes, fontsize=13.5, color=INK,
                weight="bold", va="center")
        ax.text(x, 0.055, f"{lab}·{desc}", transform=ax.transAxes, fontsize=7.2,
                color=INK3, va="center")


def _pct_bar(ax, y, label, val, pct):
    ax.text(0.035, y + 0.085, label, transform=ax.transAxes, fontsize=10.5,
            color=INK, va="center")
    val_txt = _fmt(val)
    if pct is not None:
        val_txt += f"（比历史 {pct:.0f}% 的时候贵）"
    ax.text(0.965, y + 0.085, val_txt, transform=ax.transAxes, fontsize=10.5,
            color=INK, va="center", ha="right", weight="bold")
    track_x, track_w = 0.035, 0.93
    ax.add_patch(plt.Rectangle((track_x, y - 0.005), track_w, 0.035,
                 transform=ax.transAxes, facecolor=GRID, edgecolor="none"))
    # 两端标注 便宜 / 贵
    ax.text(track_x, y - 0.07, "← 便宜", transform=ax.transAxes, fontsize=8,
            color=GOOD, va="center")
    ax.text(track_x + track_w, y - 0.07, "贵 →", transform=ax.transAxes,
            fontsize=8, color=CRIT, va="center", ha="right")
    if pct is not None:
        frac = max(0, min(100, pct)) / 100
        color = GOOD if pct <= 30 else (WARN if pct <= 70 else CRIT)
        ax.scatter([track_x + track_w * frac], [y + 0.0125], s=130, color=color,
                   edgecolors=INK, linewidths=1, transform=ax.transAxes, zorder=4)


def _score_panel(ax, scores):
    _card(ax, "四维打分", hint="每维 5 分满分")
    if not scores:
        ax.text(0.5, 0.4, "无评分数据", transform=ax.transAxes, color=INK2, ha="center")
        return
    y0 = 0.74
    for d in scores:
        ax.text(0.035, y0, d.dim, transform=ax.transAxes, fontsize=11.5,
                color=INK, va="center", weight="bold")
        hint = _DIM_HINT.get(d.dim, "")
        if hint:
            ax.text(0.035, y0 - 0.075, hint, transform=ax.transAxes, fontsize=7.5,
                    color=INK3, va="center")
        # 5 个圆点
        for k in range(5):
            filled = k < d.score
            ax.scatter([0.40 + k * 0.078], [y0], s=125,
                       color=BLUE if filled else GRID, edgecolors="none",
                       transform=ax.transAxes, zorder=3)
        ax.text(0.965, y0, f"{d.score}", transform=ax.transAxes,
                fontsize=13, color=INK, va="center", ha="right", weight="bold")
        y0 -= 0.205


def _peer_panel(ax, p: Profile, peers):
    _card(ax, "和同行比", hint="右下=又便宜又能赚")
    pts = [(pr.pe_ttm, pr.roe, pr.name or pr.code, pr.code == p.code)
           for pr in (peers or []) if pr.pe_ttm is not None and pr.roe is not None
           and pr.pe_ttm > 0]
    if len(pts) < 2:
        ax.text(0.5, 0.42, "无同行数据可比", transform=ax.transAxes, color=INK2,
                ha="center", fontsize=11)
        return
    inset = ax.inset_axes([0.15, 0.18, 0.79, 0.58])
    inset.set_facecolor(CARD)
    for sp in inset.spines.values():
        sp.set_color(GRID)
    inset.tick_params(colors=INK2, labelsize=8)
    inset.grid(True, color=GRID, linewidth=0.6, alpha=0.6)
    pes = [pe for pe, _, _, _ in pts]
    roes = [roe for _, roe, _, _ in pts]
    # 留出边距，避免点的名字标签贴边/压轴
    pe_pad = max((max(pes) - min(pes)) * 0.18, 1.0)
    roe_pad = max((max(roes) - min(roes)) * 0.22, 1.0)
    inset.set_xlim(min(pes) - pe_pad, max(pes) + pe_pad)
    inset.set_ylim(min(roes) - roe_pad, max(roes) + roe_pad * 1.4)  # 上方多留给标签
    for pe, roe, name, is_self in pts:
        inset.scatter([pe], [roe], s=200 if is_self else 110,
                      color=BLUE if is_self else GREY,
                      edgecolors=INK if is_self else "none", linewidths=1.3, zorder=3)
        inset.annotate(name, (pe, roe), fontsize=8,
                       color=INK if is_self else INK2,
                       xytext=(0, 10), textcoords="offset points", ha="center",
                       annotation_clip=False)
    inset.set_xlabel("← 便宜   贵 →   (PE)", color=INK2, fontsize=8.5)
    inset.set_ylabel("越能赚 ↑ (ROE%)", color=INK2, fontsize=8.5)


def _trend_panel(ax, closes, index_closes, p: Profile):
    _card(ax, "近一年 vs 大盘", hint="都从 100 起画")
    if not closes or len(closes) < 2:
        ax.text(0.5, 0.42, "无走势数据", transform=ax.transAxes, color=INK2, ha="center")
        return
    inset = ax.inset_axes([0.12, 0.16, 0.83, 0.60])
    inset.set_facecolor(CARD)
    for sp in inset.spines.values():
        sp.set_color(GRID)
    inset.tick_params(colors=INK2, labelsize=8)
    inset.grid(True, color=GRID, linewidth=0.6, alpha=0.6)

    base = closes[0]
    norm = [c / base * 100 for c in closes]
    x = list(range(len(norm)))
    inset.plot(x, norm, color=BLUE, linewidth=2.2, zorder=3, label="本股")
    if index_closes and len(index_closes) == len(closes):
        ib = index_closes[0]
        inorm = [c / ib * 100 for c in index_closes]
        inset.plot(x, inorm, color=INK2, linewidth=1.5, linestyle="--", zorder=2,
                   label="大盘(沪深300)")
    inset.axhline(100, color=GRID, linewidth=0.8)
    inset.legend(loc="upper left", fontsize=8, facecolor=CARD, edgecolor=GRID,
                 labelcolor=INK)
    inset.set_xticks([])

    # 直接标一年涨跌 + 相对大盘
    chg = p.price_change_1y_pct
    rel = p.price_vs_hs300_1y_pp
    if chg is not None:
        chg_c = GOOD if chg >= 0 else CRIT
        txt = f"近一年 {chg:+.0f}%"
        if rel is not None:
            word = "跑赢" if rel >= 0 else "跑输"
            txt += f"，{word}大盘 {abs(rel):.0f}%"
        ax.text(0.5, 0.06, txt, transform=ax.transAxes, fontsize=10.5,
                color=chg_c, ha="center", va="center", weight="bold")
