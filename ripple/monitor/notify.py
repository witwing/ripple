"""通知：把扫描命中推到飞书（webhook）。

- 每日汇总：一条消息列出所有命中（含触发原因）
- 强信号：confidence 高的 buy 单独醒目提示
- 无 webhook 时降级为写文件 + 返回文本，方便本地/cron 查看

飞书自定义机器人 webhook 在 config.yaml：
  monitor:
    feishu_webhook: "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
"""
from __future__ import annotations

from datetime import datetime

from ripple.core.config import Config
from ripple.core.logger import get_logger
from ripple.monitor.scan import ScanResult

log = get_logger(__name__)


def build_digest_text(res: ScanResult) -> str:
    """把扫描结果拼成一条可读文本（Markdown）。"""
    if not res.hits:
        return f"📊 Ripple 盘后扫描：扫了 {res.scanned} 支，暂无触发。"

    lines = [f"📊 **Ripple 盘后扫描** · {datetime.now().strftime('%Y-%m-%d')}",
             f"扫描 {res.scanned} 支，命中 [{len(res.hits)}] 支：", ""]

    strong = [h for h in res.hits if h.strong]
    normal = [h for h in res.hits if not h.strong]

    if strong:
        lines.append("🔥 **强信号**")
        for h in strong:
            lines.append(f"- **{h.name}({h.code})** {_action_cn(h.action)}"
                         f" 置信 {h.confidence:.0%}")
            for t in h.triggers:
                lines.append(f"    · {t.reason}")
        lines.append("")

    if normal:
        lines.append("👀 **值得关注**")
        for h in normal:
            reasons = "；".join(t.reason for t in h.triggers)
            lines.append(f"- {h.name}({h.code}) {_action_cn(h.action)}：{reasons}")

    return "\n".join(lines)


def _action_cn(a: str) -> str:
    return {"buy": "买入", "sell": "卖出", "hold": "持有", "watch": "观望"}.get(a, a)


def notify(cfg: Config, res: ScanResult) -> tuple[bool, str]:
    """推送。返回 (是否成功推送, 文本)。无 webhook 则只返回文本。"""
    text = build_digest_text(res)
    webhook = cfg.get("monitor.feishu_webhook")
    if not webhook:
        log.info("未配置 monitor.feishu_webhook，跳过推送（仅返回文本）")
        return False, text

    if not res.hits:
        # 无命中默认不打扰（可配 notify_empty）
        if not cfg.get("monitor.notify_empty", False):
            return False, text

    try:
        import httpx
        payload = {"msg_type": "text", "content": {"text": text}}
        r = httpx.post(webhook, json=payload, timeout=10)
        r.raise_for_status()
        log.info("已推送飞书")
        return True, text
    except Exception as e:  # noqa: BLE001
        log.warning(f"飞书推送失败：{e}")
        return False, text
