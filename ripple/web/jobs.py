"""进程内后台任务：跑 study/scan 不卡请求。

v1 用线程池 + 内存状态表，单机够用。将来量大可换 Celery/RQ，对外接口不变：
  submit(kind, fn) -> job_id
  get(job_id) -> {status, result, error, ...}
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

_executor = ThreadPoolExecutor(max_workers=2)
_lock = threading.Lock()


@dataclass
class Job:
    id: str
    kind: str
    status: str = "pending"      # pending | running | done | error
    result: Any = None
    error: str | None = None
    label: str = ""
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status,
                "result": self.result, "error": self.error,
                "label": self.label, "meta": self.meta}


_jobs: dict[str, Job] = {}


def submit(kind: str, fn: Callable[[], Any], label: str = "", meta: dict | None = None) -> str:
    job = Job(id=uuid.uuid4().hex[:12], kind=kind, label=label, meta=meta or {})
    with _lock:
        _jobs[job.id] = job

    def _run():
        job.status = "running"
        try:
            job.result = fn()
            job.status = "done"
        except Exception as e:  # noqa: BLE001
            job.error = str(e)
            job.status = "error"

    _executor.submit(_run)
    return job.id


def get(job_id: str) -> dict | None:
    j = _jobs.get(job_id)
    return j.to_dict() if j else None


def recent(limit: int = 20) -> list[dict]:
    with _lock:
        js = list(_jobs.values())
    return [j.to_dict() for j in js[-limit:]]
