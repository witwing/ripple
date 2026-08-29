"""akshare Provider。M1 只实现 meta.profile 和 quote 相关；其余按需扩。

原则：只做"厂商 → Ripple 内部结构"的字段映射，不做业务判断。
"""
from __future__ import annotations

from datetime import date, datetime
from time import perf_counter
from typing import Literal

import pandas as pd

from ripple.core.symbol import Symbol
from ripple.providers.base import (
    HealthStatus,
    Quote,
    TickerProfile,
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
