"""把 Profile 渲染成一张可视化仪表盘 PNG（matplotlib）。

设计原则（遵循 dataviz 规范）：
- 状态色保留给信号：good=#1a8a4a warning=#e0a300 critical=#d84340
- 主序列蓝 #2a78d6，中性灰做网格/次要文字
- 中文用 Noto Sans CJK；深色背景增强专业感
- 一张图讲清：信号灯行 + 分位条 + 四维评分 + 同行对比 + 走势
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
BG = "#16181d"          # 画布底
CARD = "#1e2128"        # 卡片底
INK = "#f2f3f5"         # 主文字
INK2 = "#9aa0aa"        # 次要文字
GRID = "#2c3038"        # 网格
BLUE = "#3987e5"        # 主序列
GOOD = "#1faf6f"
WARN = "#e0a300"
CRIT = "#e05753"
GREY = "#6b7280"

_LIGHT_COLOR = {"🟢": GOOD, "🟡": WARN, "🔴": CRIT, "⚪": GREY}


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
) -> Path:
    """渲染一张仪表盘 PNG，返回路径。"""
    signals = build_signals(profile)
    scores = build_scores(profile)

    fig = plt.figure(figsize=(11, 8.5), dpi=140)
    fig.patch.set_facecolor(BG)

    # 网格布局：标题 / 信号灯 / (分位条+评分) / (同行+走势)
    gs = fig.add_gridspec(
        4, 2, height_ratios=[0.32, 0.95, 1.5, 2.0],
        hspace=0.42, wspace=0.18,
        left=0.06, right=0.955, top=0.90, bottom=0.06,
    )

    _title(fig, profile)
    _signal_row(fig.add_subplot(gs[1, :]), signals)
    _percentile_panel(fig.add_subplot(gs[2, 0]), profile)
    _score_panel(fig.add_subplot(gs[2, 1]), scores)
    _peer_panel(fig.add_subplot(gs[3, 0]), profile, peers)
    _trend_panel(fig.add_subplot(gs[3, 1]), kline_dates, kline_closes, index_closes)

    out = Path(out_path)
    fig.savefig(out, facecolor=BG, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    return out


def _title(fig, p: Profile):
    name = p.name or p.code
    price = _fmt(p.price)
    chg = p.price_change_1d_pct
    chg_color = GOOD if (chg or 0) >= 0 else CRIT
    chg_str = f"{chg:+.2f}%" if chg is not None else "—"

    fig.text(0.06, 0.975, f"{name}", fontsize=25, color=INK, weight="bold", va="top")
    fig.text(0.06, 0.935, f"{p.code}  ·  {p.industry or '—'}", fontsize=12, color=INK2, va="top")
    # 右上角价格
    fig.text(0.955, 0.975, f"¥{price}", fontsize=25, color=INK, weight="bold",
             va="top", ha="right")
    fig.text(0.955, 0.935, chg_str, fontsize=13, color=chg_color, va="top", ha="right")


def _card(ax, title):
    ax.set_facecolor(CARD)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks([]); ax.set_yticks([])
    # 圆角卡片
    ax.add_patch(FancyBboxPatch(
        (0, 0), 1, 1, transform=ax.transAxes,
        boxstyle="round,pad=0,rounding_size=0.03",
        facecolor=CARD, edgecolor="none", zorder=-1, clip_on=False,
    ))
    if title:
        ax.text(0.03, 0.94, title, transform=ax.transAxes, fontsize=12.5,
                color=INK, weight="bold", va="top")


def _signal_row(ax, signals):
    _card(ax, None)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    if not signals:
        ax.text(0.5, 0.5, "无信号数据", transform=ax.transAxes, color=INK2,
                ha="center", va="center")
        return
    n = len(signals)
    for i, s in enumerate(signals):
        cx = (i + 0.5) / n
        color = _LIGHT_COLOR.get(s.light, GREY)
        # 圆点
        ax.scatter([cx], [0.68], s=520, color=color, edgecolors="none",
                   transform=ax.transAxes, zorder=3)
        ax.text(cx, 0.68, "", transform=ax.transAxes)
        ax.text(cx, 0.32, s.label, transform=ax.transAxes, fontsize=12.5,
                color=INK, ha="center", va="center", weight="bold")
        ax.text(cx, 0.13, s.note, transform=ax.transAxes, fontsize=8.2,
                color=INK2, ha="center", va="center")


def _percentile_panel(ax, p: Profile):
    _card(ax, "估值分位（5 年）")
    rows = [
        ("PE-TTM", p.pe_ttm, p.pe_pct_5y),
        ("PB", p.pb, p.pb_pct_5y),
    ]
    # 加几个非分位指标做水平量能条（用相对值）
    y0 = 0.66
    for label, val, pct in rows:
        _pct_bar(ax, y0, label, val, pct)
        y0 -= 0.30

    # 底部补充关键比率
    extra = [
        ("ROE", _fmt(p.roe, "%")),
        ("毛利率", _fmt(p.gross_margin, "%")),
        ("净利率", _fmt(p.net_margin, "%")),
        ("负债率", _fmt(p.debt_ratio, "%")),
    ]
    xs = [0.06, 0.30, 0.54, 0.78]
    for (lab, v), x in zip(extra, xs):
        ax.text(x, 0.16, v, transform=ax.transAxes, fontsize=13, color=INK,
                weight="bold", va="center")
        ax.text(x, 0.05, lab, transform=ax.transAxes, fontsize=8.5, color=INK2, va="center")


def _pct_bar(ax, y, label, val, pct):
    ax.text(0.03, y + 0.08, label, transform=ax.transAxes, fontsize=10.5,
            color=INK2, va="center")
    ax.text(0.97, y + 0.08, _fmt(val), transform=ax.transAxes, fontsize=11,
            color=INK, va="center", ha="right", weight="bold")
    # 轨道
    track_x, track_w = 0.03, 0.94
    ax.add_patch(plt.Rectangle((track_x, y - 0.03), track_w, 0.045,
                 transform=ax.transAxes, facecolor=GRID, edgecolor="none"))
    if pct is not None:
        frac = max(0, min(100, pct)) / 100
        # 分位低=便宜=绿，高=贵=红
        color = GOOD if pct <= 30 else (WARN if pct <= 70 else CRIT)
        ax.add_patch(plt.Rectangle((track_x, y - 0.03), track_w * frac, 0.045,
                     transform=ax.transAxes, facecolor=color, edgecolor="none"))
        ax.text(track_x + track_w * frac, y - 0.075, f"{pct:.0f}%",
                transform=ax.transAxes, fontsize=8.5, color=color,
                ha="center", va="center")


def _score_panel(ax, scores):
    _card(ax, "投资价值评分")
    if not scores:
        ax.text(0.5, 0.4, "无评分数据", transform=ax.transAxes, color=INK2, ha="center")
        return
    y0 = 0.72
    for d in scores:
        ax.text(0.03, y0, d.dim, transform=ax.transAxes, fontsize=11,
                color=INK, va="center", weight="bold")
        # 星点：5 个圆，填充 score 个
        for k in range(5):
            filled = k < d.score
            ax.scatter([0.34 + k * 0.072], [y0], s=130,
                       color=BLUE if filled else GRID, edgecolors="none",
                       transform=ax.transAxes, zorder=3)
        ax.text(0.97, y0, f"{d.score}/5", transform=ax.transAxes,
                fontsize=10, color=INK2, va="center", ha="right")
        y0 -= 0.185


def _peer_panel(ax, p: Profile, peers):
    _card(ax, "同行对比 · ROE vs PE")
    if not peers:
        ax.text(0.5, 0.45, "无同行数据", transform=ax.transAxes, color=INK2, ha="center")
        return
    # 散点：x=PE, y=ROE, 自身高亮
    pts = [(pr.pe_ttm, pr.roe, pr.name or pr.code, pr.code == p.code)
           for pr in peers if pr.pe_ttm is not None and pr.roe is not None]
    if not pts:
        ax.text(0.5, 0.45, "同行数据不足", transform=ax.transAxes, color=INK2, ha="center")
        return
    inset = ax.inset_axes([0.12, 0.16, 0.82, 0.66])
    inset.set_facecolor(CARD)
    for spine in inset.spines.values():
        spine.set_color(GRID)
    inset.tick_params(colors=INK2, labelsize=8)
    inset.grid(True, color=GRID, linewidth=0.6, alpha=0.6)
    for pe, roe, name, is_self in pts:
        inset.scatter([pe], [roe], s=200 if is_self else 110,
                      color=BLUE if is_self else GREY,
                      edgecolors=INK if is_self else "none", linewidths=1.3, zorder=3)
        inset.annotate(name, (pe, roe), fontsize=8,
                       color=INK if is_self else INK2,
                       xytext=(0, 8), textcoords="offset points", ha="center")
    inset.set_xlabel("PE-TTM", color=INK2, fontsize=9)
    inset.set_ylabel("ROE %", color=INK2, fontsize=9)


def _trend_panel(ax, dates, closes, index_closes):
    _card(ax, "近一年走势 vs 沪深300（归一化）")
    if not closes or len(closes) < 2:
        ax.text(0.5, 0.45, "无走势数据", transform=ax.transAxes, color=INK2, ha="center")
        return
    inset = ax.inset_axes([0.10, 0.16, 0.85, 0.66])
    inset.set_facecolor(CARD)
    for spine in inset.spines.values():
        spine.set_color(GRID)
    inset.tick_params(colors=INK2, labelsize=8)
    inset.grid(True, color=GRID, linewidth=0.6, alpha=0.6)

    # 归一化到 100
    base = closes[0]
    norm = [c / base * 100 for c in closes]
    x = list(range(len(norm)))
    inset.plot(x, norm, color=BLUE, linewidth=2, zorder=3, label="个股")
    if index_closes and len(index_closes) == len(closes):
        ibase = index_closes[0]
        inorm = [c / ibase * 100 for c in index_closes]
        inset.plot(x, inorm, color=INK2, linewidth=1.5, linestyle="--",
                   zorder=2, label="沪深300")
    inset.axhline(100, color=GRID, linewidth=0.8)
    inset.legend(loc="upper right", fontsize=8, facecolor=CARD,
                 edgecolor=GRID, labelcolor=INK)
    inset.set_xticks([])
