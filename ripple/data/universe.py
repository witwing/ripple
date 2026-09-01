"""全市场股票名录：从交易所名单同步到本地 SQLite，支持按代码/名称/拼音搜索。

数据源（akshare，都走非 push2 的稳定接口）：
- 上交所主板 + 科创板：stock_info_sh_name_code
- 深交所主板 + 创业板：stock_info_sz_name_code
- 北交所：stock_info_bj_name_code（不稳定，失败则跳过）

拼音用 pypinyin 生成简拼（贵州茅台→gzmt），未安装则留空不影响代码/名称搜索。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select

from ripple.core.logger import get_logger
from ripple.core.symbol import Symbol
from ripple.models import UniverseStock, session

log = get_logger(__name__)


def _pinyin_initials(name: str) -> str | None:
    try:
        from pypinyin import Style, lazy_pinyin
    except ImportError:
        return None
    try:
        parts = lazy_pinyin(name, style=Style.FIRST_LETTER, errors="ignore")
        return "".join(p[0] for p in parts if p).lower() or None
    except Exception:
        return None


def _norm_date(x) -> str | None:
    if x is None:
        return None
    if hasattr(x, "strftime"):
        return x.strftime("%Y-%m-%d")
    s = str(x).strip()
    return s or None


def sync(ak_module=None) -> tuple[int, list[str]]:
    """从交易所名单刷新 universe 表。返回 (总数, 各源状态说明)。"""
    if ak_module is None:
        import akshare as ak_module  # noqa: N813

    rows: dict[str, dict] = {}
    notes: list[str] = []

    # 上交所主板 + 科创板
    for sym_arg, board in [("主板A股", "MAIN"), ("科创板", "STAR")]:
        try:
            df = ak_module.stock_info_sh_name_code(symbol=sym_arg)
            for _, r in df.iterrows():
                code = str(r.get("证券代码") or "").strip()
                if not _valid(code):
                    continue
                rows[code] = {
                    "code": code, "name": str(r.get("证券简称") or "").strip(),
                    "exchange": "SH", "board": board,
                    "list_date": _norm_date(r.get("上市日期")), "industry": None,
                }
            notes.append(f"上交所{sym_arg} {len(df)}")
        except Exception as e:  # noqa: BLE001
            notes.append(f"上交所{sym_arg} 失败({str(e)[:30]})")

    # 深交所（主板 + 创业板）
    try:
        df = ak_module.stock_info_sz_name_code(symbol="A股列表")
        board_map = {"主板": "MAIN", "创业板": "CHINEXT"}
        for _, r in df.iterrows():
            code = str(r.get("A股代码") or "").strip()
            if not _valid(code):
                continue
            rows[code] = {
                "code": code, "name": str(r.get("A股简称") or "").strip(),
                "exchange": "SZ", "board": board_map.get(str(r.get("板块")), "MAIN"),
                "list_date": _norm_date(r.get("A股上市日期")),
                "industry": _clean(r.get("所属行业")),
            }
        notes.append(f"深交所 {len(df)}")
    except Exception as e:  # noqa: BLE001
        notes.append(f"深交所 失败({str(e)[:30]})")

    # 北交所（不稳定）
    try:
        df = ak_module.stock_info_bj_name_code()
        code_col = "证券代码" if "证券代码" in df.columns else df.columns[0]
        name_col = "证券简称" if "证券简称" in df.columns else df.columns[1]
        for _, r in df.iterrows():
            code = str(r.get(code_col) or "").strip()
            if not _valid(code):
                continue
            rows[code] = {
                "code": code, "name": str(r.get(name_col) or "").strip(),
                "exchange": "BJ", "board": "BSE",
                "list_date": None, "industry": None,
            }
        notes.append(f"北交所 {len(df)}")
    except Exception as e:  # noqa: BLE001
        notes.append(f"北交所 跳过({str(e)[:20]})")

    # 落库（全量替换）
    now = datetime.utcnow()
    with session() as s:
        s.query(UniverseStock).delete()
        for code, d in rows.items():
            s.add(UniverseStock(
                code=d["code"], name=d["name"],
                pinyin=_pinyin_initials(d["name"]),
                exchange=d["exchange"], board=d["board"],
                industry=d["industry"], list_date=d["list_date"],
                updated_at=now,
            ))
        s.commit()
    return len(rows), notes


def _valid(code: str) -> bool:
    if not (len(code) == 6 and code.isdigit()):
        return False
    try:
        Symbol.parse(code)
        return True
    except ValueError:
        return False


def _clean(x) -> str | None:
    if x is None:
        return None
    s = str(x).strip()
    return s if s and s != "nan" else None


def count() -> int:
    with session() as s:
        return s.query(UniverseStock).count()


def get(code: str) -> UniverseStock | None:
    with session() as s:
        r = s.get(UniverseStock, code)
        if r is None:
            return None
        return UniverseStock(code=r.code, name=r.name, pinyin=r.pinyin,
                             exchange=r.exchange, board=r.board,
                             industry=r.industry, list_date=r.list_date)


def search(query: str, limit: int = 20) -> list[UniverseStock]:
    """按代码前缀 / 名称包含 / 拼音前缀搜索。"""
    q = query.strip().lower()
    if not q:
        return []
    with session() as s:
        stmt = select(UniverseStock).where(or_(
            UniverseStock.code.like(f"{q}%"),
            UniverseStock.name.like(f"%{query.strip()}%"),
            UniverseStock.pinyin.like(f"{q}%"),
        )).limit(limit)
        rows = s.execute(stmt).scalars().all()
        return [UniverseStock(code=r.code, name=r.name, pinyin=r.pinyin,
                              exchange=r.exchange, board=r.board,
                              industry=r.industry, list_date=r.list_date)
                for r in rows]
