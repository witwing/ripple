"""Ripple CLI —— M1 命令入口。"""
from __future__ import annotations

import json as jsonlib
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ripple import __version__
from ripple.core import paths
from ripple.core.config import load as load_config
from ripple.core.logger import get_logger
from ripple.core.symbol import Symbol
from ripple.models import Ticker, Watch, session
from ripple.notes import indexer, search, store
from ripple.providers import cache as provider_cache
from ripple.providers import registry as _registry_module
from ripple.providers.registry import registry

app = typer.Typer(add_completion=False, help="Ripple · 观澜 — 一人投资研究、模拟与知识沉淀系统")
console = Console()
log = get_logger("ripple.cli")


def _bootstrap():
    cfg = load_config()
    if not registry._chains:
        registry.load_from_config(cfg)
    return cfg


# ---- 顶层 ----
@app.callback()
def _root(
    version: bool = typer.Option(False, "--version", help="打印版本"),
):
    if version:
        console.print(f"ripple {__version__}")
        raise typer.Exit()


# ---- watch ----
watch_app = typer.Typer(help="自选池管理")
app.add_typer(watch_app, name="watch")


@watch_app.command("add")
def watch_add(code: str = typer.Argument(..., help="6 位 A 股代码")):
    """加入自选池；同时首次拉取该票的元信息落库。"""
    cfg = _bootstrap()
    try:
        sym = Symbol.parse(code)
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)

    # 落 watch
    with session() as s:
        exists = s.get(Watch, sym.code)
        if exists is None:
            s.add(Watch(code=sym.code, added_at=datetime.utcnow()))
            s.commit()

    # 顺便拉一次 profile，让 watch add 就是最小 smoke
    try:
        profile = registry.call("meta", "profile", sym.code)
    except Exception as e:  # noqa: BLE001
        console.print(f"[yellow]![/yellow] 已加入自选，但拉取元信息失败：{e}")
        console.print("  提示：可稍后运行 `ripple providers ping` 排查数据源。")
        raise typer.Exit()

    with session() as s:
        t = s.get(Ticker, sym.code)
        if t is None:
            t = Ticker(code=sym.code)
            s.add(t)
        t.name = profile.name
        t.exchange = profile.exchange
        t.board = profile.board
        t.industry = profile.industry
        t.list_date = profile.list_date
        t.meta_json = {"total_mv": profile.total_mv, "float_mv": profile.float_mv}
        t.updated_at = datetime.utcnow()
        s.commit()

    console.print(f"[green]✓[/green] 已加入自选：[bold]{sym.code}[/bold] {profile.name} · {profile.industry or '?'}")


@watch_app.command("list")
def watch_list():
    """列出自选池。"""
    _bootstrap()
    with session() as s:
        watches = s.query(Watch).order_by(Watch.added_at).all()
        tickers = {t.code: t for t in s.query(Ticker).all()}
    if not watches:
        console.print("[dim]自选池为空。用 `ripple watch add <code>` 添加。[/dim]")
        return
    t = Table(title="自选池", show_header=True, header_style="bold")
    t.add_column("代码")
    t.add_column("名称")
    t.add_column("行业")
    t.add_column("加入时间")
    for w in watches:
        info = tickers.get(w.code)
        t.add_row(
            w.code,
            info.name if info else "-",
            (info.industry if info and info.industry else "-"),
            w.added_at.strftime("%Y-%m-%d"),
        )
    console.print(t)


@watch_app.command("remove")
def watch_remove(code: str):
    """从自选池移除。"""
    _bootstrap()
    with session() as s:
        w = s.get(Watch, code)
        if w is None:
            console.print(f"[yellow]not found:[/yellow] {code}")
            raise typer.Exit(1)
        s.delete(w)
        s.commit()
    console.print(f"[green]✓[/green] 已移除 {code}")


# ---- note ----
note_app = typer.Typer(help="自由笔记")
app.add_typer(note_app, name="note")


def _open_editor_for(initial: str) -> str:
    editor = os.environ.get("EDITOR") or shutil.which("vim") or shutil.which("vi") or shutil.which("nano")
    if not editor:
        console.print("[red]找不到 $EDITOR 也没有 vim/vi/nano。改用 `--body '...'` 或管道传入。[/red]")
        raise typer.Exit(2)
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(initial)
        tmp = f.name
    try:
        subprocess.call([editor, tmp])
        return open(tmp, encoding="utf-8").read()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


@note_app.command("new")
def note_new(
    ticker: list[str] = typer.Option([], "--ticker", "-t", help="关联 ticker，可多次"),
    theme: list[str] = typer.Option([], "--theme", help="关联主题"),
    tag: list[str] = typer.Option([], "--tag", help="打标签"),
    source: Optional[str] = typer.Option(None, "--source", help="信息来源"),
    confidence: Optional[float] = typer.Option(None, "--confidence", help="0-1"),
    body: Optional[str] = typer.Option(None, "--body", help="直接给正文（避免开编辑器）"),
):
    """新建一条笔记。优先级：--body > stdin > $EDITOR。"""
    cfg = _bootstrap()

    if body is None and not sys.stdin.isatty():
        body = sys.stdin.read()

    if body is None:
        initial = "\n\n"  # 空行让光标在正文
        body = _open_editor_for(initial)

    body = (body or "").strip()
    if not body:
        console.print("[yellow]正文为空，取消。[/yellow]")
        raise typer.Exit(1)

    # 校验 ticker
    checked_tickers: list[str] = []
    for c in ticker:
        try:
            checked_tickers.append(Symbol.parse(c).code)
        except ValueError as e:
            console.print(f"[red]✗[/red] {e}")
            raise typer.Exit(1)

    note = store.write(
        body=body,
        tickers=checked_tickers,
        themes=list(theme),
        tags=list(tag),
        source=source,
        confidence=confidence,
    )
    recomputed, n_chunks = indexer.sync_one(cfg, note)
    console.print(
        f"[green]✓[/green] 已保存 [bold]{note.id}[/bold]  "
        f"→ {note.path.relative_to(paths.home())}"
        + (f"  · 向量 {n_chunks} chunk" if recomputed and n_chunks else "")
    )


@note_app.command("recall")
def note_recall(
    query: str = typer.Argument(..., help='检索词，支持 ticker:600519 / tag:白酒'),
    k: int = typer.Option(8, "--k", help="返回条数"),
    json_out: bool = typer.Option(False, "--json", help="机器可读"),
):
    """向量 + 关键词混合检索。"""
    cfg = _bootstrap()
    hits = search.recall(cfg, query, k=k)
    if json_out:
        console.print(jsonlib.dumps(
            [
                {
                    "id": h.note_id, "score": h.score,
                    "tickers": h.tickers, "themes": h.themes, "tags": h.tags,
                    "path": h.path, "excerpt": h.excerpt,
                }
                for h in hits
            ],
            ensure_ascii=False, indent=2,
        ))
        return
    if not hits:
        console.print("[dim]没匹配到笔记。[/dim]")
        return
    t = Table(title=f"检索：{query}", show_header=True, header_style="bold")
    t.add_column("id", overflow="fold")
    t.add_column("tickers")
    t.add_column("tags")
    t.add_column("score", justify="right")
    t.add_column("摘要", overflow="fold")
    for h in hits:
        t.add_row(
            h.note_id,
            ",".join(h.tickers) or "-",
            ",".join(h.tags + h.themes) or "-",
            f"{h.score:.3f}",
            (h.excerpt or "")[:80],
        )
    console.print(t)


@note_app.command("link")
def note_link(code: str):
    """列出提及某 ticker 的所有笔记。"""
    _bootstrap()
    try:
        code = Symbol.parse(code).code
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)
    rows = indexer.notes_linked_to(code)
    if not rows:
        console.print(f"[dim]{code} 还没有关联笔记。[/dim]")
        return
    t = Table(title=f"{code} 的笔记", show_header=True, header_style="bold")
    t.add_column("id"); t.add_column("时间"); t.add_column("tags"); t.add_column("摘要", overflow="fold")
    for r in sorted(rows, key=lambda x: (x.created or datetime.min), reverse=True):
        t.add_row(
            r.id,
            r.created.strftime("%Y-%m-%d") if r.created else "-",
            ",".join((r.tags or []) + (r.themes or [])) or "-",
            (r.excerpt or "")[:80],
        )
    console.print(t)


@note_app.command("reindex")
def note_reindex():
    """全量扫描 notes/*.md，重建索引与向量。"""
    cfg = _bootstrap()
    n, r, c = indexer.reindex_all(cfg)
    console.print(f"[green]✓[/green] 索引完成：{n} 条笔记，{r} 条重算向量，共 {c} chunks。")


# ---- providers ----
providers_app = typer.Typer(help="数据源")
app.add_typer(providers_app, name="providers")


@providers_app.command("list")
def providers_list():
    """当前生效的 provider 与优先级。"""
    _bootstrap()
    mapping = registry.list_all()
    t = Table(title=f"策略：{registry._strategy}", show_header=True, header_style="bold")
    t.add_column("能力"); t.add_column("链（优先级从高到低）")
    for cap, names in mapping.items():
        t.add_row(cap, " → ".join(names) if names else "[dim]（未配置）[/dim]")
    console.print(t)


@providers_app.command("ping")
def providers_ping():
    """依次调用每个 provider 的 health()。"""
    _bootstrap()
    provs = registry.all_providers()
    if not provs:
        console.print("[yellow]没有已装载的 provider。[/yellow]")
        return
    t = Table(title="Provider Health", show_header=True, header_style="bold")
    t.add_column("provider"); t.add_column("状态"); t.add_column("延迟 ms", justify="right"); t.add_column("消息")
    for name, prov in provs.items():
        try:
            h = prov.health()
            status = "[green]OK[/green]" if h.ok else "[red]FAIL[/red]"
            t.add_row(name, status, str(h.latency_ms), h.message[:60])
        except Exception as e:  # noqa: BLE001
            t.add_row(name, "[red]FAIL[/red]", "-", str(e)[:60])
    console.print(t)


# ---- cache ----
cache_app = typer.Typer(help="Provider 缓存")
app.add_typer(cache_app, name="cache")


@cache_app.command("clear")
def cache_clear(
    provider: Optional[str] = typer.Option(None, "--provider", help="只清某个 provider 的缓存"),
):
    n = provider_cache.clear(provider)
    console.print(f"[green]✓[/green] 已清除 {n} 个缓存文件"
                  + (f"（{provider}）" if provider else "（全部）"))


# ---- study ----
@app.command("study")
def study_cmd(
    code: str = typer.Argument(..., help="6 位 A 股代码"),
    refresh: bool = typer.Option(False, "--refresh", help="绕过缓存重新拉数据"),
    no_llm: bool = typer.Option(False, "--no-llm", help="dry-run 模式，不调用 LLM"),
):
    """深挖单票：拉数据 → 召回笔记 → 生成 Brief + Advice。"""
    from ripple.analyze.study import study as run_study
    from ripple.llm import get_client, make_narrator

    cfg = _bootstrap()
    if refresh:
        provider_cache.clear()

    client = get_client(cfg, force_dry_run=no_llm)
    narrator = None if client.name == "dry-run" else make_narrator(cfg, client)

    try:
        result = run_study(cfg, code, refresh=refresh, narrator=narrator)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]✗[/red] study 失败：{e}")
        raise typer.Exit(1)

    console.print()
    console.print(f"[green]✓[/green] Brief → {result.brief_path.relative_to(paths.home())}")
    if result.chart_path:
        console.print(f"[green]✓[/green] 图表 → {result.chart_path.relative_to(paths.home())}")
    p = result.profile
    tp = Table(show_header=False, box=None, pad_edge=False)
    tp.add_row("价格", f"{p.price if p.price is not None else '-'}"
                       f"  ({p.price_change_1d_pct:+.2f}%)" if p.price_change_1d_pct is not None else "")
    tp.add_row("走势",
               f"1m {p.price_change_1m_pct}  3m {p.price_change_3m_pct}  1y {p.price_change_1y_pct}")
    tp.add_row("估值",
               f"PE_TTM {p.pe_ttm} (5Y {p.pe_pct_5y}%)  PB {p.pb} (5Y {p.pb_pct_5y}%)  DV {p.dv_ratio}%")
    tp.add_row("财务", f"营收同比 {p.revenue_yoy_pct}%  净利同比 {p.net_profit_yoy_pct}%")
    tp.add_row("召回", f"{len(result.context.recalled_notes)} 条笔记")
    console.print(tp)

    a = result.advice
    console.print()
    console.print(
        f"[bold]结论[/bold]  action={a.action}  size={a.size_pct}%  "
        f"conf={a.confidence:.2f}  horizon={a.horizon_days}d"
    )
    if a.horizon_views:
        hv = a.horizon_views
        console.print(
            f"[bold]周期[/bold]  短期 {hv.get('short','-')}  ·  "
            f"中期 {hv.get('mid','-')}  ·  长期 {hv.get('long','-')}"
        )
    if a.value_scores:
        vs = a.value_scores
        def _stars(n): return "★" * int(n) + "☆" * (5 - int(n))
        parts = []
        for key, label in [("valuation", "估值"), ("growth", "成长"),
                           ("quality", "质量"), ("capital", "资金")]:
            if key in vs:
                parts.append(f"{label} {_stars(vs[key])}")
        if parts:
            console.print("[bold]评分[/bold]  " + "   ".join(parts))
    console.print(f"[dim]{a.rationale}[/dim]")
    console.print(f"[dim]advice_id: {result.advice_id}[/dim]")


if __name__ == "__main__":
    app()
