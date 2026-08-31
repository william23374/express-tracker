from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from express.models import CompanyHint, TrackResult


class ProviderError(Exception):
    """Raised when a provider call fails."""


@runtime_checkable
class TrackingProvider(Protocol):
    name: str

    def detect_company(self, tracking_number: str) -> list[CompanyHint]:
        """Return possible companies for a tracking number (best first)."""

    def track(
        self,
        tracking_number: str,
        company: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> TrackResult:
        """Query tracking status and history."""


_REGISTRY: dict[str, type] = {}


def register(name: str):
    def decorator(cls):
        _REGISTRY[name] = cls
        return cls

    return decorator


def available_providers() -> list[str]:
    return sorted(_REGISTRY)


def create_provider(name: str, **kwargs) -> TrackingProvider:
    if name not in _REGISTRY:
        known = ", ".join(available_providers()) or "(none)"
        raise ProviderError(f"Unknown provider '{name}'. Available: {known}")
    return _REGISTRY[name](**kwargs)


def load_builtin_providers() -> None:
    from express.providers import alapi as _alapi  # noqa: F401
    from express.providers import apizero as _apizero  # noqa: F401
    from express.providers import fallback as _fallback  # noqa: F401
    from express.providers import huawei_jm as _huawei_jm  # noqa: F401
    from express.providers import huawei_kd100 as _huawei_kd100  # noqa: F401
    from express.providers import mock as _mock  # noqa: F401
