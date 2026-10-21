"""Alert source adapters.

Adapters are the only place that know a source's wire format. They return a validated
``NormalizedAlert`` and never touch persistence, correlation, or notifications.
"""

from __future__ import annotations

from app.adapters.alertmanager import AlertmanagerAdapter
from app.adapters.base import AdapterValidationError, AlertSourceAdapter, NormalizedAlert
from app.adapters.cloudwatch import CloudWatchAdapter
from app.adapters.registry import ADAPTERS, get_adapter, supported_sources

__all__ = [
    "ADAPTERS",
    "AdapterValidationError",
    "AlertSourceAdapter",
    "AlertmanagerAdapter",
    "CloudWatchAdapter",
    "NormalizedAlert",
    "get_adapter",
    "supported_sources",
]
