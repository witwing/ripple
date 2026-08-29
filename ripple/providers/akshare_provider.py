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
            # 用 sina 的指数日线做连通性检查（走 finance.sina.com.cn，比 push2.eastmoney 稳）
            df = self._ak.stock_zh_index_daily(symbol="sh000001")
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
        """从 sina 快照 + stock_value_em 组合出 profile。
        push2.eastmoney.com 常被反爬，所以避开走 eastmoney 的接口。
        """
        sym = Symbol.parse(code)
        name = sym.code
        total_mv: float | None = None
        float_mv: float | None = None

        # 名字：sina 快照第一列就是股票简称
        try:
            import requests
            r = requests.get(
                f"https://hq.sinajs.cn/list={sym.to_akshare()}",
                headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
                timeout=8,
            )
            r.encoding = "gbk"
            text = r.text
            if "=" in text and '"' in text:
                payload = text.split('"')[1]
                fields = payload.split(",")
                if fields and fields[0]:
                    name = fields[0]
        except Exception:
            pass

        # 市值：stock_value_em 最近一行
        try:
            df = self._ak.stock_value_em(symbol=sym.code)
            if df is not None and not df.empty:
                last = df.iloc[-1]
                total_mv = _to_float(last.get("总市值"))
                float_mv = _to_float(last.get("流通市值"))
        except Exception:
            pass

        return TickerProfile(
            code=sym.code,
            name=name,
            exchange=sym.exchange,
            board=sym.board,
            industry=None,  # sina 快照不含行业；后续如需要走另一接口补
            list_date=None,
            total_mv=total_mv,
            float_mv=float_mv,
        )

    # ---- quote ----
    @cached("snapshot", ttl_hours=0.1)
    def snapshot(self, code: str) -> Quote:
        """走 sina 快照（hq.sinajs.cn），避开被反爬的 stock_zh_a_spot_em。"""
        sym = Symbol.parse(code)
        try:
            import requests
            r = requests.get(
                f"https://hq.sinajs.cn/list={sym.to_akshare()}",
                headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
                timeout=8,
            )
            r.encoding = "gbk"
        except Exception as e:
            raise RuntimeError(f"sina 快照请求失败：{e}") from e

        # 格式：var hq_str_sh600519="名称,今开,昨收,现价,最高,最低,买1,卖1,成交量,成交额,...,日期,时间,00,...";
        if '"' not in r.text:
            raise RuntimeError(f"sina 快照返回异常：{r.text[:100]}")
        payload = r.text.split('"')[1]
        f = payload.split(",")
        if len(f) < 10:
            raise RuntimeError(f"sina 快照字段不足：{payload[:100]}")

        return Quote(
            code=sym.code,
            ts=datetime.utcnow(),
            price=_to_float(f[3]) or 0.0,
            open=_to_float(f[1]),
            high=_to_float(f[4]),
            low=_to_float(f[5]),
            prev_close=_to_float(f[2]),
            volume=_to_float(f[8]),
            amount=_to_float(f[9]),
        )

    @cached("daily_kline", ttl_hours=12)
    def daily_kline(self, code: str, start: date, end: date) -> pd.DataFrame:
        """走 sina 日线 stock_zh_a_daily，避开被反爬的 stock_zh_a_hist。"""
        sym = Symbol.parse(code)
        try:
            df = self._ak.stock_zh_a_daily(
                symbol=sym.to_akshare(),
                adjust="qfq",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        except Exception as e:
            raise RuntimeError(f"sina 拉 K 线失败：{e}") from e
        if df is None or df.empty:
            return empty_kline()

        # sina 列：date/open/high/low/close/volume/amount/outstanding_share/turnover
        # 已经是英文了，只需补 turnover_pct 别名
        if "turnover" in df.columns and "turnover_pct" not in df.columns:
            df = df.copy()
            df["turnover_pct"] = df["turnover"] * 100  # sina 返回是比例
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
        """走 stock_value_em（返回历史 PE_TTM / PB / 市销率等，最新一行 + 5Y 分位）。"""
        sym = Symbol.parse(code)
        try:
            df = self._ak.stock_value_em(symbol=sym.code)
        except Exception as e:
            raise RuntimeError(f"akshare 拉估值失败：{e}") from e
        if df is None or df.empty:
            return Valuation(code=sym.code, ts=datetime.utcnow())

        date_col = "数据日期" if "数据日期" in df.columns else _first_present(
            df.columns, ["trade_date", "date", "日期"]
        )
        pe_col = _first_present(df.columns, ["PE(TTM)", "pe_ttm", "PE", "市盈率-TTM", "市盈率"])
        pb_col = _first_present(df.columns, ["市净率", "pb", "PB"])
        # stock_value_em 没有股息率，交给 sina 快照或后续接口
        dv_col = _first_present(df.columns, ["dv_ratio", "股息率"])

        if date_col:
            df = df.sort_values(date_col)
        latest = df.iloc[-1]

        # 5 年分位
        recent = df
        if date_col:
            five_years_ago = datetime.now() - timedelta(days=365 * 5)
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
