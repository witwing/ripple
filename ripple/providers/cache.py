"""磁盘缓存 + 简单重试。装饰 Provider 方法。

缓存 key = (provider, method, args_hash, date_bucket)
date_bucket 由 TTL 决定：TTL >= 24h 用日期，其他按小时/分钟切。
value = pickle 落盘。
"""
from __future__ import annotations

import hashlib
import pickle
import time
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from ripple.core import paths
from ripple.core.logger import get_logger

log = get_logger(__name__)


def _serialize_arg(x: Any) -> str:
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    return repr(x)


def _bucket(ttl_hours: float) -> str:
    now = datetime.utcnow()
    if ttl_hours >= 24:
        return now.strftime("%Y%m%d")
    if ttl_hours >= 1:
        return now.strftime("%Y%m%d_%H")
    # < 1h：分钟级
    minute_slot = (now.minute // max(1, int(ttl_hours * 60))) * max(1, int(ttl_hours * 60))
    return now.strftime("%Y%m%d_%H") + f"_{minute_slot:02d}"


def cache_key(provider: str, method: str, args: tuple, kwargs: dict, ttl_hours: float) -> Path:
    payload = "|".join(
        [provider, method, *(_serialize_arg(a) for a in args),
         *(f"{k}={_serialize_arg(v)}" for k, v in sorted(kwargs.items()))]
    )
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    bucket = _bucket(ttl_hours)
    return paths.cache_dir(provider) / method / bucket / f"{h}.pkl"


def cached(method_name: str, ttl_hours: float, retries: int = 2):
    """装饰 Provider 实例方法。第一次调用会 mkdir、写盘；命中就 unpickle 返回。"""
    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(self, *args, **kwargs):
            prov_name = getattr(self, "name", self.__class__.__name__)
            path = cache_key(prov_name, method_name, args, kwargs, ttl_hours)
            if path.exists():
                try:
                    with path.open("rb") as f:
                        return pickle.load(f)
                except Exception as e:  # noqa: BLE001
                    log.debug(f"cache 读失败，重跑：{e}")

            last_exc: Exception | None = None
            for attempt in range(retries + 1):
                try:
                    result = fn(self, *args, **kwargs)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("wb") as f:
                        pickle.dump(result, f)
                    return result
                except Exception as e:  # noqa: BLE001
                    last_exc = e
                    if attempt < retries:
                        wait = 2 ** attempt
                        log.warning(f"{prov_name}.{method_name} 失败：{e}；{wait}s 后重试")
                        time.sleep(wait)
            raise last_exc  # type: ignore[misc]
        return wrapper
    return deco


def clear(provider: str | None = None) -> int:
    """清缓存。返回删除的文件数。"""
    root = paths.cache_dir(provider) if provider else paths.cache_dir()
    if not root.exists():
        return 0
    count = 0
    for p in root.rglob("*.pkl"):
        try:
            p.unlink()
            count += 1
        except OSError:
            pass
    return count
