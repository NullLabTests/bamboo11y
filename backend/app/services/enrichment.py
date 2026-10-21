"""Alert enrichment from the service catalog.

The enrichment is snapshotted on the alert at ingest time so ownership/tier changes later
do not rewrite incident history. Read models use this snapshot and the current catalog can
provide live topology separately.
"""

from __future__ import annotations

from typing import Any

from app.adapters.base import NormalizedAlert
from app.services.catalog import Catalog


def enrich_alert(alert: NormalizedAlert, catalog: Catalog) -> dict[str, Any]:
    service = catalog.get(alert.service)
    if service is None:
        return {
            "service_found": False,
            "catalog_version": catalog.version,
            "service_name": alert.service,
            "owner": "Unmapped",
            "team": "unmapped",
            "tier": "unknown",
            "environments": [],
            "dependencies": [],
            "dependents": [],
            "warning": (
                "Service is not present in config/services.yaml. Ownership and topology "
                "context are unavailable until the catalog is updated."
            ),
        }
    return {
        "service_found": True,
        "catalog_version": catalog.version,
        "service_name": service.name,
        "owner": service.owner,
        "team": service.team,
        "tier": service.tier,
        "environments": list(service.environments),
        "dependencies": list(service.depends_on),
        "dependents": [item.id for item in catalog.direct_dependents(alert.service)],
        "repository": service.repository,
        "runbook": service.runbook,
    }
