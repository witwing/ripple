import pytest

from ripple.providers.base import HealthStatus, ProviderError
from ripple.providers.registry import ProviderRegistry


class Cap:
    """占位 capability 类型，仅用于注册键。"""


class GoodProv:
    name = "good"

    def method(self, x):
        return f"good:{x}"

    def health(self) -> HealthStatus:
        return HealthStatus(provider=self.name, ok=True, latency_ms=1)


class BadProv:
    name = "bad"

    def method(self, x):
        raise RuntimeError("no")

    def health(self) -> HealthStatus:
        return HealthStatus(provider=self.name, ok=False, latency_ms=1)


def _reg(*provs, strategy="fallback"):
    r = ProviderRegistry()
    r._strategy = strategy
    r._chains["cap"] = [(p.name, p) for p in provs]
    for p in provs:
        r._providers[p.name] = p
    return r


def test_fallback_uses_next_on_failure():
    r = _reg(BadProv(), GoodProv())
    assert r.call("cap", "method", "x") == "good:x"


def test_all_fail_raises():
    r = _reg(BadProv(), BadProv())
    with pytest.raises(ProviderError):
        r.call("cap", "method", "x")


def test_primary_does_not_fallback():
    r = _reg(BadProv(), GoodProv(), strategy="primary")
    with pytest.raises(ProviderError):
        r.call("cap", "method", "x")


def test_missing_capability():
    r = ProviderRegistry()
    with pytest.raises(ProviderError):
        r.call("nonexistent", "method")
