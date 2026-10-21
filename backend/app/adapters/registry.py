"""Adapter registry provides source discovery and helpful unsupported-source errors."""

from __future__ import annotations

from app.adapters.alertmanager import AlertmanagerAdapter
from app.adapters.base import AlertSourceAdapter
from app.adapters.cloudwatch import CloudWatchAdapter
from app.adapters.open_integration import OpenIntegrationAdapter
from app.constants import Source

ADAPTERS: dict[str, AlertSourceAdapter] = {
    Source.PROMETHEUS.value: AlertmanagerAdapter(),
    Source.CLOUDWATCH.value: CloudWatchAdapter(),
    Source.OPEN_INTEGRATION.value: OpenIntegrationAdapter(),
}


def get_adapter(source: str) -> AlertSourceAdapter | None:
    return ADAPTERS.get(source)


def supported_sources() -> list[str]:
    return sorted(ADAPTERS)
