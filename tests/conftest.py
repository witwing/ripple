"""共享 fixtures：给每个测试独立 RIPPLE_HOME。"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_HOME", str(tmp_path))
    # 强制重新导入涉及全局状态的模块
    import ripple.core.paths as paths
    import ripple.core.config as config
    import ripple.models as models
    import ripple.notes.embed as embed_mod
    importlib.reload(paths)
    importlib.reload(config)
    importlib.reload(models)
    embed_mod._model = None
    embed_mod._chroma = None
    embed_mod._collection = None
    embed_mod._warned_missing = False
    # 清空 provider registry 单例
    from ripple.providers.registry import registry
    registry._chains.clear()
    registry._providers.clear()
    registry._failed.clear()
    yield tmp_path
