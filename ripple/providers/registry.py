"""Provider 注册表 + fallback 路由。

- 按 (capability, provider) 注册
- config 里的顺序即优先级
- get(capability, method_name) 返回一个 callable，内部自动 fallback
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from ripple.core.logger import get_logger
from ripple.providers.base import CAPABILITIES, ProviderError

log = get_logger(__name__)


class ProviderRegistry:
    def __init__(self) -> None:
        # capability_name -> list[(name, provider)]，按 config 顺序
        self._chains: dict[str, list[tuple[str, Any]]] = defaultdict(list)
        # provider_name -> provider（去重存储）
        self._providers: dict[str, Any] = {}
        # provider_name -> 已尝试实例化时的错误消息（None 表示成功）
        self._failed: dict[str, str] = {}
        self._strategy: str = "fallback"

    def load_from_config(self, cfg) -> None:
        """按 config.providers 配置装配。惰性导入以避免非必要依赖启动失败。"""
        self._strategy = cfg.strategy
        for cap_name in CAPABILITIES:
            names = cfg.providers_for(cap_name)
            for pname in names:
                prov = self._instantiate(pname)
                if prov is None:
                    continue
                self._chains[cap_name].append((pname, prov))

    def _instantiate(self, name: str) -> Any | None:
        if name in self._providers:
            return self._providers[name]
        if name in self._failed:
            return None  # 曾失败过，静默跳过（第一次已 warn）
        try:
            if name == "akshare":
                from ripple.providers.akshare_provider import AkshareProvider

                prov = AkshareProvider()
            else:
                log.warning(f"未知 provider: {name}（跳过）")
                self._failed[name] = "unknown"
                return None
        except Exception as e:
            log.warning(f"provider {name} 初始化失败：{e}")
            self._failed[name] = str(e)
            return None
        self._providers[name] = prov
        return prov

    def list_all(self) -> dict[str, list[str]]:
        return {cap: [n for n, _ in chain] for cap, chain in self._chains.items()}

    def chain(self, capability: str) -> list[tuple[str, Any]]:
        return list(self._chains.get(capability, []))

    def all_providers(self) -> dict[str, Any]:
        return dict(self._providers)

    def call(self, capability: str, method: str, *args, **kwargs) -> Any:
        """在 capability 的注册链上按策略调用 method。

        fallback: 主源失败自动降级；全失败抛最后一个异常
        primary : 只用第一个
        """
        chain = self._chains.get(capability, [])
        if not chain:
            raise ProviderError(f"没有可用的 provider 满足能力: {capability}")

        strategy = self._strategy
        if strategy == "primary":
            chain = chain[:1]

        last_exc: Exception | None = None
        for name, prov in chain:
            fn: Callable | None = getattr(prov, method, None)
            if fn is None:
                log.debug(f"provider {name} 未实现 {method}，跳过")
                continue
            try:
                result = fn(*args, **kwargs)
                if strategy != "cross_check":
                    return result
                # cross_check 暂未实现校验逻辑，v1 fallback 到主源
                return result
            except Exception as e:  # noqa: BLE001
                log.warning(f"provider {name}.{method} 失败：{e}；尝试下一个")
                last_exc = e
                continue

        raise ProviderError(f"{capability}.{method} 全链失败") from last_exc


# 单例
registry = ProviderRegistry()
