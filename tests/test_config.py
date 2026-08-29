def test_load_creates_default(tmp_path, monkeypatch):
    # isolate_home fixture 已注入 RIPPLE_HOME 并 reload 了模块，所以在函数内 import
    from ripple.core.config import load
    cfg = load()
    assert cfg.strategy == "fallback"
    assert cfg.providers_for("quote") == ["akshare"]
    cfg2 = load()
    assert cfg2.providers_for("meta") == ["akshare"]
    assert cfg.get("cache.ttl_hours.daily_kline") == 12


def test_deep_merge_preserves_user_keys(tmp_path):
    from ripple.core import paths
    from ripple.core.config import load
    import yaml
    cfg_path = paths.config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.safe_dump({
        "providers": {"quote": ["akshare", "tushare"]},
        "cache": {"ttl_hours": {"daily_kline": 999}},
    }), encoding="utf-8")
    cfg = load()
    # 用户键保留
    assert cfg.providers_for("quote") == ["akshare", "tushare"]
    assert cfg.get("cache.ttl_hours.daily_kline") == 999
    # 未覆盖的默认键仍在
    assert cfg.get("cache.ttl_hours.snapshot") == 0.1
