"""笔记索引器：扫描 notes/*.md，写 note_index 表，同步向量库。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from ripple.core.config import Config
from ripple.core.logger import get_logger
from ripple.models import NoteIndex, session
from ripple.notes import embed, store
from ripple.notes.chunk import chunk as chunk_body

log = get_logger(__name__)


def upsert_index(note: store.Note) -> NoteIndex:
    with session() as s:
        existing = s.get(NoteIndex, note.id)
        if existing is None:
            existing = NoteIndex(id=note.id, path=str(note.path))
            s.add(existing)
        existing.path = str(note.path)
        existing.tickers = list(note.tickers)
        existing.themes = list(note.themes)
        existing.tags = list(note.tags)
        existing.confidence = note.confidence
        existing.created = note.created if not isinstance(note.created, str) else None
        existing.updated = datetime.utcnow()
        existing.file_mtime = note.path.stat().st_mtime
        existing.content_hash = note.content_hash
        existing.excerpt = note.excerpt
        s.commit()
        return existing


def upsert_vectors(cfg: Config, note: store.Note) -> int:
    if not embed.available(cfg):
        return 0
    # 先清掉这条 note 的旧向量
    embed.delete_note(note.id)
    max_tokens = int(cfg.get("embed.chunk_token_threshold", 400))
    chunks = chunk_body(note.body, max_tokens=max_tokens)
    if not chunks:
        return 0
    for i, ch in enumerate(chunks):
        cid = note.id if len(chunks) == 1 else f"{note.id}#{i}"
        embed.upsert(
            cfg,
            chunk_id=cid,
            text=ch,
            metadata={
                "note_id": note.id,
                "tickers": ",".join(note.tickers),
                "tags": ",".join(note.tags + note.themes),
                "chunk_idx": i,
            },
        )
    return len(chunks)


def sync_one(cfg: Config, note: store.Note) -> tuple[bool, int]:
    """索引 + 向量。返回 (是否重算了向量, chunk 数)。"""
    with session() as s:
        existing = s.get(NoteIndex, note.id)
        need_vec = (
            existing is None
            or existing.content_hash != note.content_hash
            or existing.file_mtime != note.path.stat().st_mtime
        )
    upsert_index(note)
    if need_vec:
        n = upsert_vectors(cfg, note)
        return True, n
    return False, 0


def reindex_all(cfg: Config) -> tuple[int, int, int]:
    """全量重建：扫描所有 md，重写索引 + 向量。返回 (笔记数, 重算向量数, chunk 总数)。"""
    # 向量库整体清空更快，避免残留
    if embed.available(cfg):
        embed.reset()
    # 清空 note_index
    with session() as s:
        s.query(NoteIndex).delete()
        s.commit()

    n_notes = 0
    n_recomputed = 0
    n_chunks = 0
    for note in store.iter_notes():
        n_notes += 1
        recomputed, c = sync_one(cfg, note)
        if recomputed:
            n_recomputed += 1
            n_chunks += c
    return n_notes, n_recomputed, n_chunks


def notes_linked_to(code: str) -> list[NoteIndex]:
    """列出提及某 ticker 的所有笔记。"""
    with session() as s:
        rows = s.execute(select(NoteIndex)).scalars().all()
    return [r for r in rows if code in (r.tickers or [])]
