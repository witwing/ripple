"""SQLAlchemy 模型。索引层：单一事实源是文件（notes/*.md）与外部数据源，DB 只做缓存与索引。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from ripple.core import paths


class Base(DeclarativeBase):
    pass


class Ticker(Base):
    """股票元数据缓存。"""
    __tablename__ = "ticker"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(64))
    exchange: Mapped[str | None] = mapped_column(String(4))
    board: Mapped[str | None] = mapped_column(String(16))
    industry: Mapped[str | None] = mapped_column(String(64))
    list_date: Mapped[str | None] = mapped_column(String(10))
    meta_json: Mapped[dict | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class Watch(Base):
    """自选池。"""
    __tablename__ = "watch"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    note: Mapped[str | None] = mapped_column(Text)


class UniverseStock(Base):
    """全市场股票名录（可搜索）。由 `ripple universe sync` 从交易所名单刷新。"""
    __tablename__ = "universe_stock"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(64), index=True)
    pinyin: Mapped[str | None] = mapped_column(String(64), index=True)  # 简拼，如 gzmt
    exchange: Mapped[str | None] = mapped_column(String(4))
    board: Mapped[str | None] = mapped_column(String(16))
    industry: Mapped[str | None] = mapped_column(String(64))
    list_date: Mapped[str | None] = mapped_column(String(10))
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class Snapshot(Base):
    """时间序列快照：任何一次对外抓的原始数据都可以落这里。"""
    __tablename__ = "snapshot"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(8), index=True)
    ts: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # quote | fin | val | ann | news
    payload_json: Mapped[dict | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(32))


class NoteIndex(Base):
    """笔记索引：真身在 notes/*.md，这里只做检索与关联。"""
    __tablename__ = "note_index"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    path: Mapped[str] = mapped_column(String(512))
    tickers: Mapped[list | None] = mapped_column(JSON)
    themes: Mapped[list | None] = mapped_column(JSON)
    tags: Mapped[list | None] = mapped_column(JSON)
    confidence: Mapped[float | None] = mapped_column(Float)
    created: Mapped[datetime | None]
    updated: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    file_mtime: Mapped[float | None] = mapped_column(Float)
    content_hash: Mapped[str | None] = mapped_column(String(32))
    excerpt: Mapped[str | None] = mapped_column(Text)  # 前 200 字，供 recall 展示


# M2+ 模型（先建表方便一版打完；无对应业务代码前不会被用到）
class Brief(Base):
    __tablename__ = "brief"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(8), index=True)
    created: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    model: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(String(512))
    cited_note_ids: Mapped[list | None] = mapped_column(JSON)


class Advice(Base):
    __tablename__ = "advice"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    brief_id: Mapped[str | None] = mapped_column(ForeignKey("brief.id"))
    ticker: Mapped[str] = mapped_column(String(8), index=True)
    action: Mapped[str] = mapped_column(String(16))  # buy/sell/hold/watch
    size_pct: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    rationale: Mapped[str | None] = mapped_column(Text)
    created: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class Portfolio(Base):
    __tablename__ = "portfolio"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    cash: Mapped[float] = mapped_column(Float, default=0.0)
    init_cash: Mapped[float] = mapped_column(Float, default=0.0)
    created: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    nav_json: Mapped[dict | None] = mapped_column(JSON)


class Position(Base):
    """当前持仓，买卖后即时维护。"""
    __tablename__ = "position"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolio.id"), index=True)
    code: Mapped[str] = mapped_column(String(8), index=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)
    updated: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class Trade(Base):
    __tablename__ = "trade"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolio.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(8), index=True)
    side: Mapped[str] = mapped_column(String(4))  # buy/sell
    price: Mapped[float] = mapped_column(Float)
    qty: Mapped[int] = mapped_column(Integer)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float | None] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    advice_id: Mapped[str | None] = mapped_column(ForeignKey("advice.id"))


class NavPoint(Base):
    """净值快照点，画曲线用。"""
    __tablename__ = "nav_point"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolio.id"), index=True)
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    nav: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    holdings_value: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class Review(Base):
    __tablename__ = "review"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    advice_id: Mapped[str] = mapped_column(ForeignKey("advice.id"))
    actual_return_pct: Mapped[float | None] = mapped_column(Float)
    verdict: Mapped[str | None] = mapped_column(String(16))
    lesson_note_id: Mapped[str | None] = mapped_column(ForeignKey("note_index.id"))
    created: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class TriggerLog(Base):
    """监控触发记录，用于去重（同一 code+rule N 天内只提醒一次）。"""
    __tablename__ = "trigger_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(8), index=True)
    rule: Mapped[str] = mapped_column(String(32), index=True)  # 触发规则 key
    reason: Mapped[str | None] = mapped_column(Text)           # 人读的触发原因
    advice_id: Mapped[str | None] = mapped_column(String(48))
    notified: Mapped[bool] = mapped_column(default=False)
    created: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)


# ---- 引擎与 Session ----
_engine = None


def get_engine():
    global _engine
    if _engine is None:
        paths.ensure_layout()
        _engine = create_engine(f"sqlite:///{paths.db_path()}", future=True)
        Base.metadata.create_all(_engine)
    return _engine


def session() -> Session:
    return Session(get_engine())
