"""akshare Provider。M1 只实现 meta.profile 和 quote 相关；M2 补 fundamental/disclosure/news。

原则：只做"厂商 → Ripple 内部结构"的字段映射，不做业务判断。
akshare 字段名易漂移，所有映射都要能容忍"字段消失"（返回 None / NaN）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from time import perf_counter
from typing import Any, Literal

import pandas as pd

from ripple.core.symbol import Symbol
from ripple.providers.base import (
    Announcement,
    HealthStatus,
    NewsItem,
    Quote,
    TickerProfile,
    Valuation,
    empty_kline,
    normalize_kline,
)
from ripple.providers.cache import cached


class AkshareProvider:
    name = "akshare"

    def __init__(self) -> None:
        # 延迟导入：即便未安装 akshare，其他模块也能 import providers 包
        try:
            import akshare as ak  # type: ignore
        except ImportError as e:
            raise ImportError("需要 pip install akshare") from e
        self._ak = ak

    # ---- health ----
    def health(self) -> HealthStatus:
        t0 = perf_counter()
        try:
            # 取一次上证指数即时行情做连通性检查（akshare 的 stock_zh_index_spot 一般较稳）
            df = self._ak.stock_zh_index_spot_em(symbol="上证系列指数")
            ok = df is not None and not df.empty
            msg = "OK" if ok else "空返回"
        except Exception as e:  # noqa: BLE001
            ok = False
            msg = str(e)
        latency = int((perf_counter() - t0) * 1000)
        return HealthStatus(provider=self.name, ok=ok, latency_ms=latency, message=msg)

    # ---- meta ----
    @cached("profile", ttl_hours=240)
    def profile(self, code: str) -> TickerProfile:
        sym = Symbol.parse(code)
        # akshare 有多个"个股信息"接口，`stock_individual_info_em` 相对稳定
        try:
            info = self._ak.stock_individual_info_em(symbol=sym.code)
        except Exception as e:
            raise RuntimeError(f"akshare 拉取 {sym.code} 元信息失败：{e}") from e

        kv: dict[str, str] = {}
        if info is not None and not info.empty:
            for _, row in info.iterrows():
                kv[str(row.iloc[0])] = str(row.iloc[1])

        # 字段在不同 akshare 版本略有差异，兼容几种命名
        name = kv.get("股票简称") or kv.get("名称") or kv.get("股票名称") or sym.code
        industry = kv.get("行业") or kv.get("所处行业")
        list_date = _normalize_date(kv.get("上市时间") or kv.get("上市日期"))
        total_mv = _to_float(kv.get("总市值"))
        float_mv = _to_float(kv.get("流通市值"))

        return TickerProfile(
            code=sym.code,
            name=name,
            exchange=sym.exchange,
            board=sym.board,
            industry=industry,
            list_date=list_date,
            total_mv=total_mv,
            float_mv=float_mv,
        )

    # ---- quote ----
    @cached("snapshot", ttl_hours=0.1)
    def snapshot(self, code: str) -> Quote:
        sym = Symbol.parse(code)
        try:
            df = self._ak.stock_zh_a_spot_em()  # 全市场快照，一次调用
        except Exception as e:
            raise RuntimeError(f"akshare 拉即时行情失败：{e}") from e
        if df is None or df.empty:
            raise RuntimeError("akshare 即时行情为空")
        row = df.loc[df["代码"] == sym.code]
        if row.empty:
            raise RuntimeError(f"未在 A 股即时行情中找到 {sym.code}")
        r = row.iloc[0]
        return Quote(
            code=sym.code,
            ts=datetime.utcnow(),
            price=_to_float(r.get("最新价")) or 0.0,
            open=_to_float(r.get("今开")),
            high=_to_float(r.get("最高")),
            low=_to_float(r.get("最低")),
            prev_close=_to_float(r.get("昨收")),
            volume=_to_float(r.get("成交量")),
            amount=_to_float(r.get("成交额")),
        )

    @cached("daily_kline", ttl_hours=12)
    def daily_kline(self, code: str, start: date, end: date) -> pd.DataFrame:
        sym = Symbol.parse(code)
        try:
            df = self._ak.stock_zh_a_hist(
                symbol=sym.code,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )
        except Exception as e:
            raise RuntimeError(f"akshare 拉 K 线失败：{e}") from e
        if df is None or df.empty:
            return empty_kline()

        # akshare 中文列 → Ripple 英文列
        col_map = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
            "换手率": "turnover_pct",
        }
        df = df.rename(columns=col_map)
        return normalize_kline(df, source=self.name)

    # ---- fundamental ----
    @cached("financial_reports", ttl_hours=240)
    def financial_reports(
        self, code: str, kind: Literal["income", "balance", "cash"], periods: int = 8
    ) -> pd.DataFrame:
        sym = Symbol.parse(code)
        # akshare 的三张表接口按财报期返回；不同版本函数名有：
        #   stock_financial_report_sina(stock, symbol) — sina, 稳定
        #   stock_financial_abstract_ths — 同花顺, 但需要 sh/sz 前缀
        # 优先 sina。
        sina_map = {"income": "利润表", "balance": "资产负债表", "cash": "现金流量表"}
        try:
            df = self._ak.stock_financial_report_sina(
                stock=sym.to_akshare(), symbol=sina_map[kind]
            )
        except Exception as e:
            raise RuntimeError(f"akshare 拉 {kind} 财报失败：{e}") from e
        if df is None or df.empty:
            return pd.DataFrame()

        # sina 返回按报告期为列的宽表；这里保持原样但只留最近 periods 期
        # 首列一般是"报告日"或"项目"，先做转置判断
        if "报告日" in df.columns:
            # 长表：报告日 + 各项目
            df = df.sort_values("报告日", ascending=False).head(periods)
        else:
            # 宽表：列名 = 报告期
            date_like_cols = [c for c in df.columns if str(c).count("-") == 2 or str(c).isdigit()]
            keep = date_like_cols[:periods]
            df = df[[df.columns[0], *keep]] if keep else df
        return df

    @cached("valuation", ttl_hours=12)
    def valuation(self, code: str) -> Valuation:
        sym = Symbol.parse(code)
        # 用个股指标 stock_a_indicator_lg，返回历史 PE/PB/DV，我们取最新一行 + 计算 5 年分位
        try:
            df = self._ak.stock_a_indicator_lg(symbol=sym.code)
        except Exception as e:
            raise RuntimeError(f"akshare 拉估值失败：{e}") from e
        if df is None or df.empty:
            return Valuation(code=sym.code, ts=datetime.utcnow())

        # 兼容列名：trade_date / date / 日期
        date_col = _first_present(df.columns, ["trade_date", "date", "日期"])
        pe_col = _first_present(df.columns, ["pe", "pe_ttm", "市盈率", "市盈率-TTM"])
        pb_col = _first_present(df.columns, ["pb", "市净率"])
        dv_col = _first_present(df.columns, ["dv_ratio", "股息率"])

        if date_col:
            df = df.sort_values(date_col)
        latest = df.iloc[-1]

        # 5 年分位
        five_years_ago = datetime.now() - timedelta(days=365 * 5)
        recent = df
        if date_col:
            try:
                recent = df[pd.to_datetime(df[date_col]) >= pd.Timestamp(five_years_ago)]
            except Exception:
                recent = df

        return Valuation(
            code=sym.code,
            ts=datetime.utcnow(),
            pe_ttm=_to_float(latest.get(pe_col)) if pe_col else None,
            pb=_to_float(latest.get(pb_col)) if pb_col else None,
            dv_ratio=_to_float(latest.get(dv_col)) if dv_col else None,
            pe_pct_5y=_percentile_of_last(recent, pe_col) if pe_col else None,
            pb_pct_5y=_percentile_of_last(recent, pb_col) if pb_col else None,
        )

    # ---- disclosure ----
    @cached("announcements", ttl_hours=6)
    def announcements(self, code: str, since: date) -> list[Announcement]:
        sym = Symbol.parse(code)
        # akshare 有 stock_notice_report(symbol="全部", date="YYYYMMDD") — 面向全市场按日拉
        # 直接按 code 拉的接口稳定性差；v1 用 stock_zh_a_disclosure_relation_cninfo/巨潮
        results: list[Announcement] = []
        try:
            # 巨潮接口：按公司拉最近公告
            df = self._ak.stock_zh_a_disclosure_report_cninfo(
                symbol=sym.code,
                market="沪深京",
                start_date=since.strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"),
            )
        except Exception as e:
            # 静默返回空，让上层用 fallback
            return results
        if df is None or df.empty:
            return results

        title_col = _first_present(df.columns, ["公告标题", "标题"])
        url_col = _first_present(df.columns, ["公告链接", "链接", "url"])
        time_col = _first_present(df.columns, ["公告时间", "公告日期", "时间"])
        kind_col = _first_present(df.columns, ["公告类型", "类型"])

        for _, row in df.iterrows():
            title = str(row.get(title_col, "")).strip() if title_col else ""
            if not title:
                continue
            results.append(
                Announcement(
                    code=sym.code,
                    title=title,
                    url=str(row.get(url_col, "")) if url_col else "",
                    publish_time=_to_datetime(row.get(time_col)) or datetime.utcnow(),
                    kind=str(row.get(kind_col)) if kind_col else None,
                )
            )
        return results

    # ---- news ----
    @cached("news", ttl_hours=1)
    def news(self, code: str, since: date, limit: int = 50) -> list[NewsItem]:
        sym = Symbol.parse(code)
        results: list[NewsItem] = []
        try:
            df = self._ak.stock_news_em(symbol=sym.code)
        except Exception:
            return results
        if df is None or df.empty:
            return results

        title_col = _first_present(df.columns, ["新闻标题", "标题"])
        time_col = _first_present(df.columns, ["发布时间", "时间"])
        url_col = _first_present(df.columns, ["新闻链接", "链接", "url"])
        source_col = _first_present(df.columns, ["文章来源", "来源"])
        summary_col = _first_present(df.columns, ["新闻内容", "摘要"])

        for _, row in df.iterrows():
            title = str(row.get(title_col, "")).strip() if title_col else ""
            if not title:
                continue
            pub = _to_datetime(row.get(time_col)) or datetime.utcnow()
            if pub.date() < since:
                continue
            results.append(
                NewsItem(
                    code=sym.code,
                    title=title,
                    url=str(row.get(url_col, "")) if url_col else "",
                    publish_time=pub,
                    source=str(row.get(source_col, "eastmoney")) if source_col else "eastmoney",
                    summary=(str(row.get(summary_col))[:200] if summary_col else None),
                )
            )
            if len(results) >= limit:
                break
        return results


def _first_present(columns, candidates: list[str]) -> str | None:
    cols = set(columns)
    for c in candidates:
        if c in cols:
            return c
    return None


def _percentile_of_last(df: pd.DataFrame, col: str) -> float | None:
    """最新值在给定序列中的百分位（0-100）。"""
    if col not in df.columns or df.empty:
        return None
    series = pd.to_numeric(df[col], errors="coerce").dropna()
    if series.empty:
        return None
    last = series.iloc[-1]
    pct = float((series <= last).mean() * 100)
    return round(pct, 1)


def _to_datetime(x: Any) -> datetime | None:
    if x is None:
        return None
    if isinstance(x, datetime):
        return x
    s = str(x).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return pd.to_datetime(s).to_pydatetime()
    except Exception:
        return None


def _to_float(x) -> float | None:
    if x is None:
        return None
    try:
        s = str(x).replace(",", "").strip()
        if not s or s in ("-", "--", "None", "nan"):
            return None
        # 兼容"1.23亿" / "4567万"
        if s.endswith("亿"):
            return float(s[:-1]) * 1e8
        if s.endswith("万"):
            return float(s[:-1]) * 1e4
        return float(s)
    except (ValueError, TypeError):
        return None


def _normalize_date(s: str | None) -> str | None:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s
