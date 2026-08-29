"""Embedding：懒加载 bge-small-zh + Chroma persistent client。

第一次调用时才加载模型，避免 CLI 冷启动过慢；模型未装时降级为纯关键词检索。
"""
from __future__ import annotations

from typing import Iterable

from ripple.core import paths
from ripple.core.config import Config
from ripple.core.logger import get_logger

log = get_logger(__name__)


_model = None
_chroma = None
_collection = None
_warned_missing = False

COLLECTION_NAME = "notes"


def _get_model(cfg: Config):
    global _model, _warned_missing
    if _model is not None:
        return _model
    model_name = cfg.get("embed.model", "BAAI/bge-small-zh-v1.5")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        if not _warned_missing:
            log.warning("sentence-transformers 未安装，向量检索关闭；混合检索退化为关键词过滤")
            _warned_missing = True
        return None
    log.info(f"加载 embedding 模型：{model_name}（首次会下载权重，耐心等）")
    _model = SentenceTransformer(model_name)
    return _model


def _get_collection():
    global _chroma, _collection
    if _collection is not None:
        return _collection
    try:
        import chromadb
    except ImportError:
        log.warning("chromadb 未安装，向量检索关闭")
        return None
    paths.ensure_layout()
    _chroma = chromadb.PersistentClient(path=str(paths.vectors_dir()))
    _collection = _chroma.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def available(cfg: Config) -> bool:
    return _get_model(cfg) is not None and _get_collection() is not None


def upsert(cfg: Config, chunk_id: str, text: str, metadata: dict) -> None:
    model = _get_model(cfg)
    coll = _get_collection()
    if model is None or coll is None:
        return
    vec = model.encode([text], normalize_embeddings=True).tolist()[0]
    coll.upsert(ids=[chunk_id], embeddings=[vec], documents=[text], metadatas=[metadata])


def delete_note(note_id: str) -> None:
    coll = _get_collection()
    if coll is None:
        return
    try:
        coll.delete(where={"note_id": note_id})
    except Exception:
        pass


def query(cfg: Config, text: str, k: int = 20) -> list[tuple[str, float, dict]]:
    """返回 [(chunk_id, similarity, metadata), ...]，分数越大越相关。"""
    model = _get_model(cfg)
    coll = _get_collection()
    if model is None or coll is None:
        return []
    vec = model.encode([text], normalize_embeddings=True).tolist()[0]
    res = coll.query(query_embeddings=[vec], n_results=k)
    out: list[tuple[str, float, dict]] = []
    ids = (res.get("ids") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    for cid, dist, meta in zip(ids, dists, metas):
        # cosine distance in chroma ∈ [0,2]；相似度 = 1 - dist/2
        sim = 1.0 - float(dist) / 2.0
        out.append((cid, sim, meta or {}))
    return out


def reset() -> None:
    """清空向量库（reindex 时用）。"""
    global _chroma, _collection
    coll = _get_collection()
    if coll is None:
        return
    try:
        _chroma.delete_collection(COLLECTION_NAME)  # type: ignore[union-attr]
    except Exception:
        pass
    _collection = None
    _get_collection()
