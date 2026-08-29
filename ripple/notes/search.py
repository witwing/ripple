"""混合检索：向量 top-K + 关键词/标签命中 → RRF 融合 → 去 chunk 重 → top-N。"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select

from ripple.core.config import Config
from ripple.models import NoteIndex, session
from ripple.notes import embed


@dataclass
class Hit:
    note_id: str
    score: float
    tickers: list[str]
    themes: list[str]
    tags: list[str]
    excerpt: str
    path: str


def _parse_query(q: str) -> tuple[str, set[str], set[str]]:
    """极简 query parser：
    - `ticker:600519` → 精确匹配 tickers
    - `tag:白酒` → 精确匹配 tags 或 themes
    - 其余进向量
    """
    text_parts: list[str] = []
    tickers: set[str] = set()
    tags: set[str] = set()
    for tok in q.split():
        if ":" in tok:
            k, v = tok.split(":", 1)
            k = k.lower()
            if k in ("t", "ticker"):
                tickers.add(v)
                continue
            if k in ("tag", "theme", "topic"):
                tags.add(v)
                continue
        text_parts.append(tok)
    return " ".join(text_parts).strip(), tickers, tags


def _keyword_candidates(text: str, tickers: set[str], tags: set[str]) -> list[str]:
    """从 SQLite index 里粗筛：文本包含关键字 / tickers 命中 / tags 命中。

    文本 term 会同时对 excerpt / tags / themes / tickers 做包含匹配。
    """
    with session() as s:
        rows = s.execute(select(NoteIndex)).scalars().all()
    hits: list[tuple[str, float]] = []
    q_terms = [t for t in text.split() if len(t) >= 2]
    for row in rows:
        score = 0.0
        rt = set(row.tickers or [])
        rtags = set(row.tags or []) | set(row.themes or [])
        if tickers and tickers & rt:
            score += 2.0
        if tags and tags & rtags:
            score += 1.5
        excerpt_l = (row.excerpt or "").lower()
        joined_tags = " ".join(rtags | rt).lower()
        for term in q_terms:
            tl = term.lower()
            if tl in excerpt_l:
                score += 0.3
            if tl in joined_tags:
                score += 0.8  # 标签/主题/ticker 命中权重更高
        if score > 0:
            hits.append((row.id, score))
    hits.sort(key=lambda x: -x[1])
    return [nid for nid, _ in hits]


def _load_index(note_ids: Iterable[str]) -> dict[str, NoteIndex]:
    ids = list(dict.fromkeys(note_ids))
    if not ids:
        return {}
    with session() as s:
        rows = s.execute(select(NoteIndex).where(NoteIndex.id.in_(ids))).scalars().all()
    return {r.id: r for r in rows}


def recall(cfg: Config, query: str, k: int = 8) -> list[Hit]:
    text, tickers, tags = _parse_query(query)

    # 向量：一条 note 可能出多个 chunk，先按 note_id 去重取最高分
    vec_ranking: list[str] = []
    if text and embed.available(cfg):
        raw = embed.query(cfg, text, k=20)
        best_by_note: dict[str, float] = {}
        for cid, sim, meta in raw:
            nid = meta.get("note_id") or cid.split("#", 1)[0]
            if sim > best_by_note.get(nid, -1e9):
                best_by_note[nid] = sim
        vec_ranking = [nid for nid, _ in sorted(best_by_note.items(), key=lambda x: -x[1])]

    # 关键词
    kw_ranking = _keyword_candidates(text, tickers, tags)

    # RRF 融合
    K = 60
    scores: dict[str, float] = defaultdict(float)
    for i, nid in enumerate(vec_ranking):
        scores[nid] += 1.0 / (K + i + 1)
    for i, nid in enumerate(kw_ranking):
        scores[nid] += 1.0 / (K + i + 1)

    if not scores:
        return []

    fused = sorted(scores.items(), key=lambda x: -x[1])[:k]
    idx = _load_index([nid for nid, _ in fused])

    hits: list[Hit] = []
    for nid, sc in fused:
        row = idx.get(nid)
        if row is None:
            continue
        hits.append(
            Hit(
                note_id=nid,
                score=sc,
                tickers=list(row.tickers or []),
                themes=list(row.themes or []),
                tags=list(row.tags or []),
                excerpt=row.excerpt or "",
                path=row.path,
            )
        )
    return hits
