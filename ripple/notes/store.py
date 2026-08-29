"""笔记文件 CRUD：读写 .md（带 frontmatter），生成 ID，同步索引。"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import frontmatter

from ripple.core import paths


@dataclass
class Note:
    id: str
    path: Path
    created: datetime
    tickers: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    source: str | None = None
    confidence: float | None = None
    body: str = ""

    @property
    def excerpt(self) -> str:
        text = self.body.strip().replace("\n", " ")
        return text[:200]

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()[:16]


def new_id(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"note_{now.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"


def path_for(note_id: str, now: datetime | None = None) -> Path:
    now = now or datetime.now()
    return paths.notes_dir() / now.strftime("%Y") / now.strftime("%m") / f"{note_id}.md"


def write(
    body: str,
    tickers: Iterable[str] = (),
    themes: Iterable[str] = (),
    tags: Iterable[str] = (),
    source: str | None = None,
    confidence: float | None = None,
    now: datetime | None = None,
) -> Note:
    now = now or datetime.now().astimezone()
    nid = new_id(now)
    p = path_for(nid, now)
    p.parent.mkdir(parents=True, exist_ok=True)

    metadata = {
        "id": nid,
        "created": now.isoformat(),
        "tickers": list(tickers),
        "themes": list(themes),
        "tags": list(tags),
    }
    if source:
        metadata["source"] = source
    if confidence is not None:
        metadata["confidence"] = confidence

    post = frontmatter.Post(body, **metadata)
    p.write_text(frontmatter.dumps(post, sort_keys=False), encoding="utf-8")

    return Note(
        id=nid,
        path=p,
        created=now,
        tickers=list(tickers),
        themes=list(themes),
        tags=list(tags),
        source=source,
        confidence=confidence,
        body=body,
    )


def load(path: Path) -> Note:
    text = path.read_text(encoding="utf-8")
    post = frontmatter.loads(text)
    meta = post.metadata

    created = meta.get("created")
    if isinstance(created, str):
        try:
            created = datetime.fromisoformat(created)
        except ValueError:
            created = datetime.fromtimestamp(path.stat().st_mtime)
    elif isinstance(created, datetime):
        pass
    else:
        created = datetime.fromtimestamp(path.stat().st_mtime)

    return Note(
        id=str(meta.get("id") or path.stem),
        path=path,
        created=created,
        tickers=[str(x) for x in meta.get("tickers", []) or []],
        themes=[str(x) for x in meta.get("themes", []) or []],
        tags=[str(x) for x in meta.get("tags", []) or []],
        source=meta.get("source"),
        confidence=meta.get("confidence"),
        body=post.content,
    )


def iter_notes() -> Iterable[Note]:
    root = paths.notes_dir()
    if not root.exists():
        return
    for p in sorted(root.rglob("*.md")):
        try:
            yield load(p)
        except Exception:
            continue
