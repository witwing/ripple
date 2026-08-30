"""Narrator：把 BriefContext 变成简报 markdown。live 走 LLM，dry-run 走模板。"""
from __future__ import annotations

import json
from pathlib import Path

from ripple.analyze.narrative import BriefContext, render_dryrun_brief
from ripple.core.config import Config
from ripple.llm.client import DryRunClient, LLMClient


_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def _render_prompt(template: str, ctx: BriefContext) -> str:
    payload = json.dumps(
        {
            "ticker": ctx.ticker,
            "profile": ctx.profile,
            "recent_kline_summary": ctx.recent_kline_summary,
            "relative_summary": ctx.relative_summary,
            "capital_summary": ctx.capital_summary,
            "consensus_summary": ctx.consensus_summary,
            "peers": ctx.peers,
            "announcements": ctx.announcements,
            "news": ctx.news,
            "recalled_notes": ctx.recalled_notes,
            "user_stance": ctx.user_stance,
        },
        ensure_ascii=False,
        indent=2,
    )
    return template.replace("{{context_json}}", payload)


def make_narrator(cfg: Config, client: LLMClient):
    """返回一个 (BriefContext) -> (markdown, model_id) 的可调用对象。"""
    is_dry = isinstance(client, DryRunClient)
    system_prompt = _load_prompt("briefer.md")

    def narrate(ctx: BriefContext) -> tuple[str, str]:
        if is_dry:
            return render_dryrun_brief(ctx), "dry-run"
        user = _render_prompt(system_prompt, ctx)
        # 优先用 client 自身的 default_model（get_client 已经处理过 env / config 优先级）
        model_id = getattr(getattr(client, "_settings", None), "default_model", None) \
            or str(cfg.get("llm.briefer", "claude-sonnet-5"))
        text = client.complete(
            system="你是严谨的股票研究员，输出中文 Markdown。",
            user=user,
            model=model_id,
            max_tokens=4096,
        )
        return text, model_id

    return narrate
