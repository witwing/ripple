"""触发规则：判断一次 study 结果是否"值得通知"。

v1 两条规则（config 可开关/调阈值）：
- valuation_low：估值进入 5Y 低分位（PE 或 PB < 阈值）且非次新股
- action_upgrade：LLM 结论较上一次升级（watch→hold→buy 方向），且置信度达标

每条规则命中返回一个 Trigger（含 rule key + 人读原因 + 重要度）。
"""
from __future__ import annotations

from dataclasses import dataclass

from ripple.analyze.advisor import ParsedAdvice
from ripple.analyze.dashboard import _valuation_percentile_unreliable
from ripple.analyze.profile import Profile

# 动作强度排序（用于判断"升级"）
_ACTION_RANK = {"sell": 0, "watch": 1, "hold": 2, "buy": 3}


@dataclass
class Trigger:
    rule: str          # 规则 key
    reason: str        # 人读原因
    strong: bool = False  # 是否强信号（单独推送）


@dataclass
class RuleConfig:
    valuation_low_enabled: bool = True
    valuation_pct_threshold: float = 20.0   # PE/PB 5Y 分位低于此触发
    action_upgrade_enabled: bool = True
    action_min_confidence: float = 0.6       # 升级到 buy 且置信度达标才算强

    @classmethod
    def from_cfg(cls, cfg) -> "RuleConfig":
        g = cfg.get("monitor.rules", {}) or {}
        return cls(
            valuation_low_enabled=g.get("valuation_low_enabled", True),
            valuation_pct_threshold=float(g.get("valuation_pct_threshold", 20.0)),
            action_upgrade_enabled=g.get("action_upgrade_enabled", True),
            action_min_confidence=float(g.get("action_min_confidence", 0.6)),
        )


def evaluate(profile: Profile, advice: ParsedAdvice,
             prev_action: str | None, rc: RuleConfig) -> list[Trigger]:
    """对一支票的最新 study 结果跑规则，返回命中的 Trigger 列表。"""
    triggers: list[Trigger] = []

    # 规则 1：估值到位
    if rc.valuation_low_enabled and not _valuation_percentile_unreliable(profile):
        # 绝对高估的（PE>100 或 PE<0）不算便宜，直接跳过
        pe_ok = profile.pe_ttm is not None and 0 < profile.pe_ttm <= 100
        hits = []
        if pe_ok and profile.pe_pct_5y is not None \
                and profile.pe_pct_5y < rc.valuation_pct_threshold:
            hits.append(f"PE 处 5Y {profile.pe_pct_5y:.0f}% 低分位")
        if profile.pb_pct_5y is not None and profile.pb_pct_5y < rc.valuation_pct_threshold:
            hits.append(f"PB 处 5Y {profile.pb_pct_5y:.0f}% 低分位")
        if hits:
            triggers.append(Trigger(
                rule="valuation_low",
                reason="估值到位：" + "，".join(hits),
                strong=False,
            ))

    # 规则 2：动作升级
    if rc.action_upgrade_enabled and prev_action:
        cur_rank = _ACTION_RANK.get(advice.action, 1)
        prev_rank = _ACTION_RANK.get(prev_action, 1)
        if cur_rank > prev_rank:
            strong = advice.action == "buy" and advice.confidence >= rc.action_min_confidence
            triggers.append(Trigger(
                rule="action_upgrade",
                reason=f"结论升级：{prev_action} → {advice.action}"
                       f"（置信度 {advice.confidence:.0%}）",
                strong=strong,
            ))

    return triggers
