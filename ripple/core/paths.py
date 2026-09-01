"""Ripple 数据目录与路径解析。

默认 `~/.ripple/`，可用环境变量 `RIPPLE_HOME` 覆盖。
用户敢把整个目录 git 起来，我们就得让路径稳定、无隐藏文件（除 `.git`）。
"""
from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    """Ripple 用户数据根目录。"""
    override = os.environ.get("RIPPLE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".ripple"


def ensure_layout() -> Path:
    """确保数据目录结构存在，返回 home。首次运行时自动建。"""
    root = home()
    for sub in ("notes", "reports", "portfolios", "vectors", "cache"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def config_path() -> Path:
    return home() / "config.yaml"


def db_path() -> Path:
    return home() / "ripple.db"


def notes_dir() -> Path:
    return home() / "notes"


def vectors_dir() -> Path:
    return home() / "vectors"


def cache_dir(provider: str | None = None) -> Path:
    p = home() / "cache"
    return p / provider if provider else p


def briefs_dir() -> Path:
    return home() / "briefs"


def reports_dir() -> Path:
    """按股票归档的报告根目录。"""
    return home() / "reports"


def report_dir(code: str) -> Path:
    """某支股票的报告目录，如 reports/600519/。"""
    return reports_dir() / code


def portfolios_dir() -> Path:
    return home() / "portfolios"
