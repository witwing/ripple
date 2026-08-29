import time

from ripple.providers import cache as pc


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.calls = 0

    @pc.cached("fetch", ttl_hours=24)
    def fetch(self, x):
        self.calls += 1
        return {"x": x, "n": self.calls}


class FlakyProvider:
    name = "flaky"

    def __init__(self, fails=1):
        self._fails = fails
        self.calls = 0

    @pc.cached("go", ttl_hours=1, retries=2)
    def go(self):
        self.calls += 1
        if self.calls <= self._fails:
            raise RuntimeError("boom")
        return "ok"


def test_cache_hits(tmp_path):
    p = FakeProvider()
    r1 = p.fetch("a")
    r2 = p.fetch("a")
    assert r1 == r2
    assert p.calls == 1  # 第二次命中缓存

    r3 = p.fetch("b")
    assert r3["x"] == "b"
    assert p.calls == 2


def test_cache_clear(tmp_path):
    p = FakeProvider()
    p.fetch("a")
    p.fetch("b")
    n = pc.clear("fake")
    assert n >= 1
    # 清完再次调用会真的重新跑
    p.fetch("a")
    assert p.calls == 3


def test_retry_then_succeed(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)
    p = FlakyProvider(fails=1)
    assert p.go() == "ok"
    assert p.calls == 2
