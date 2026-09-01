"""批量扫描：遍历自选池，跑 study，评估规则，去重，汇总命中。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select

from ripple.analyze.study import StudyResult, study
from ripple.core.config import Config
from ripple.core.logger import get_logger
from ripple.models import Advice, TriggerLog, Watch, session
from ripple.monitor.rules import RuleConfig, Trigger, evaluate

log = get_logger(__name__)


@dataclass
class ScanHit:
    code: str
    name: str
    action: str
    confidence: float
    triggers: list[Trigger]
    chart_path: str | None
    digest: str
    @property
    def strong(self) -> bool:
        return any(t.strong for t in self.triggers)


@dataclass
class ScanResult:
    scanned: int = 0
    hits: list[ScanHit] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _prev_action(code: str) -> str | None:
    """该票上一条 advice 的 action（本次 study 之前）。"""
    with session() as s:
        row = s.execute(
            select(Advice).where(Advice.ticker == code).order_by(Advice.created.desc())
        ).scalars().first()
        return row.action if row else None


def _recently_triggered(code: str, rule: str, dedup_days: int) -> bool:
    cutoff = datetime.utcnow() - timedelta(days=dedup_days)
    with session() as s:
        row = s.execute(
            select(TriggerLog).where(
                TriggerLog.code == code, TriggerLog.rule == rule,
                TriggerLog.created >= cutoff,
            )
        ).scalars().first()
        return row is not None


def _log_trigger(code: str, t: Trigger, advice_id: str):
    with session() as s:
        s.add(TriggerLog(code=code, rule=t.rule, reason=t.reason,
                         advice_id=advice_id, notified=True,
                         created=datetime.utcnow()))
        s.commit()


def _watchlist() -> list[str]:
    with session() as s:
        return [w.code for w in s.query(Watch).order_by(Watch.added_at).all()]


def scan(cfg: Config, narrator=None, dedup_days: int = 3,
         codes: list[str] | None = None) -> ScanResult:
    """扫描自选池（或指定 codes）。narrator=None 则 dry-run。"""
    rc = RuleConfig.from_cfg(cfg)
    watch = codes if codes is not None else _watchlist()
    res = ScanResult()

    for code in watch:
        prev = _prev_action(code)
        try:
            r: StudyResult = study(cfg, code, narrator=narrator)
        except Exception as e:  # noqa: BLE001
            log.warning(f"{code} study 失败：{e}")
            res.errors.append(f"{code}: {e}")
            continue
        res.scanned += 1

        triggers = evaluate(r.profile, r.advice, prev, rc)
        # 去重：过滤掉近期已提醒过的同规则
        fresh = [t for t in triggers if not _recently_triggered(code, t.rule, dedup_days)]
        if not fresh:
            continue
        for t in fresh:
            _log_trigger(code, t, r.advice_id)
        res.hits.append(ScanHit(
            code=code, name=(r.profile.name or code),
            action=r.advice.action, confidence=r.advice.confidence,
            triggers=fresh,
            chart_path=str(r.chart_path) if r.chart_path else None,
            digest=r.digest,
        ))
        log.info(f"{code} 命中 {len(fresh)} 条触发")

    return res
