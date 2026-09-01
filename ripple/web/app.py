"""FastAPI 应用：JSON API（稳定契约）+ Jinja 页面 + 图片服务。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ripple import service
from ripple.core import paths
from ripple.web import jobs

_HERE = Path(__file__).parent
_env = Environment(
    loader=FileSystemLoader(str(_HERE / "templates")),
    autoescape=select_autoescape(["html"]),
)


def _render(name: str, **ctx) -> HTMLResponse:
    return HTMLResponse(_env.get_template(name).render(**ctx))


def create_app() -> FastAPI:
    app = FastAPI(title="Ripple 观澜", docs_url="/api/docs")

    static_dir = _HERE / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ========== JSON API（稳定对外契约）==========

    @app.get("/api/watch")
    def api_watch():
        return service.list_watch()

    @app.post("/api/watch/{code}")
    def api_watch_add(code: str):
        try:
            return service.add_watch(code)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/watch/{code}")
    def api_watch_remove(code: str):
        return service.remove_watch(code)

    @app.get("/api/search")
    def api_search(q: str, limit: int = 20):
        return service.search_stocks(q, limit=limit)

    @app.get("/api/stock/{code}")
    def api_stock(code: str):
        try:
            return service.stock_reports(code)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/study/{code}")
    def api_study(code: str, no_llm: bool = False):
        from ripple.analyze.study import study as run_study
        from ripple.core.config import load as load_config
        from ripple.llm import get_client, make_narrator
        from ripple.providers.registry import registry

        cfg = load_config()
        if not registry._chains:
            registry.load_from_config(cfg)
        client = get_client(cfg, force_dry_run=no_llm)
        narrator = None if client.name == "dry-run" else make_narrator(cfg, client)

        def _job():
            r = run_study(cfg, code, narrator=narrator)
            return {"code": code, "advice": r.advice.action,
                    "confidence": r.advice.confidence,
                    "chart": bool(r.chart_path)}
        job_id = jobs.submit("study", _job, label=f"分析 {code}")
        return {"job_id": job_id}

    @app.post("/api/scan")
    def api_scan(no_llm: bool = False, notify: bool = False):
        from ripple.core.config import load as load_config
        from ripple.llm import get_client, make_narrator
        from ripple.monitor import notify as notifier
        from ripple.monitor.scan import scan as run_scan
        from ripple.providers.registry import registry

        cfg = load_config()
        if not registry._chains:
            registry.load_from_config(cfg)
        client = get_client(cfg, force_dry_run=no_llm)
        narrator = None if client.name == "dry-run" else make_narrator(cfg, client)

        def _job():
            res = run_scan(cfg, narrator=narrator,
                           dedup_days=int(cfg.get("monitor.dedup_days", 3)))
            text = notifier.build_digest_text(res)
            if notify:
                notifier.notify(cfg, res)
            return {"scanned": res.scanned, "hits": len(res.hits), "text": text}
        job_id = jobs.submit("scan", _job, label="批量扫描")
        return {"job_id": job_id}

    @app.get("/api/jobs/{job_id}")
    def api_job(job_id: str):
        j = jobs.get(job_id)
        if j is None:
            raise HTTPException(404, "job not found")
        return j

    @app.get("/api/portfolio")
    def api_portfolio():
        return service.portfolio_status() or {}

    @app.get("/api/portfolio/trades")
    def api_trades(code: str | None = None):
        return service.portfolio_trades(code=code)

    @app.post("/api/portfolio/buy")
    def api_buy(code: str, qty: int, price: float | None = None,
                advice_id: str | None = None):
        try:
            return service.sim_buy(code, qty, price, advice_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, str(e))

    @app.post("/api/portfolio/sell")
    def api_sell(code: str, qty: int, price: float | None = None,
                 advice_id: str | None = None):
        try:
            return service.sim_sell(code, qty, price, advice_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, str(e))

    @app.post("/api/portfolio/init")
    def api_pf_init(cash: float = 1_000_000.0):
        return service.sim_init(cash)

    @app.get("/api/monitor/triggers")
    def api_triggers(days: int = 7):
        return service.recent_triggers(days=days)

    @app.get("/api/monitor/config")
    def api_monitor_config():
        return service.monitor_config()

    # 报告图片
    @app.get("/report/{code}/{name}")
    def report_file(code: str, name: str):
        f = paths.report_dir(code) / name
        if not f.exists():
            raise HTTPException(404, "not found")
        return FileResponse(f)

    # ========== 页面（Jinja）==========

    @app.get("/", response_class=HTMLResponse)
    def page_home():
        return _render("home.html", watch=service.list_watch(),
                       universe=service.universe_status())

    @app.get("/stock/{code}", response_class=HTMLResponse)
    def page_stock(code: str):
        return _render("stock.html", data=service.stock_reports(code))

    @app.get("/portfolio", response_class=HTMLResponse)
    def page_portfolio():
        return _render("portfolio.html", pf=service.portfolio_status(),
                       trades=service.portfolio_trades())

    @app.get("/monitor", response_class=HTMLResponse)
    def page_monitor():
        return _render("monitor.html", triggers=service.recent_triggers(),
                       cfg=service.monitor_config())

    return app
