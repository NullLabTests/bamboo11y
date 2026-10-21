#!/usr/bin/env python3
"""Static validation for configuration and delivery assets.

This intentionally checks the things that are easy to break by hand but expensive to
discover at runtime: catalog graph integrity, documented settings, Compose wiring, CI
workflow shape, and obvious committed secrets.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.services.catalog import load_catalog  # noqa: E402

SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "generic API key assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{24,}['\"]"
    ),
}
SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "coverage",
    ".pytest_cache",
    ".ruff_cache",
    "data",
    "__pycache__",
}
SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".woff",
    ".woff2",
    ".pdf",
    ".db",
    ".sqlite",
}


class ValidationError(RuntimeError):
    pass


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ValidationError(f"missing file: {path.relative_to(ROOT)}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValidationError(f"invalid YAML in {path.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{path.relative_to(ROOT)} must contain a YAML mapping")
    return value


def validate_catalog() -> None:
    catalog = load_catalog(ROOT / "config" / "services.yaml")
    if len(catalog.services) < 3:
        raise ValidationError("catalog must contain at least three services for the demo")
    if not catalog.edges():
        raise ValidationError("catalog must contain at least one dependency edge")
    for service in catalog.services:
        if not service.environments:
            raise ValidationError(f"service {service.id} has no environments")
        if not service.runbook and service.tier == "critical":
            # Not fatal, but the validator surfaces it so operators can decide.
            print(f"  note: critical service {service.id} has no runbook link")
    print(
        f"  catalog: {len(catalog.services)} services, {len(catalog.edges())} edges, "
        f"environments={','.join(catalog.environments())}"
    )


def validate_settings() -> None:
    env_file = ROOT / ".env.example"
    fields = {f"BAMBOO11Y_{name.upper()}" for name in Settings.model_fields}
    documented: set[str] = set()
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0].strip()
            if key.startswith("BAMBOO11Y_"):
                documented.add(key)
    unknown = sorted(documented - fields)
    if unknown:
        raise ValidationError(
            ".env.example documents settings the application does not define: " + ", ".join(unknown)
        )
    missing = sorted(fields - documented - {"BAMBOO11Y_APP_NAME", "BAMBOO11Y_DATABASE_ECHO"})
    if missing:
        print(f"  note: settings not shown in .env.example: {', '.join(missing)}")
    settings = Settings(_env_file=env_file)
    if settings.correlation_window_minutes <= 0:
        raise ValidationError("correlation window must be positive")
    if settings.max_alerts_per_request < 1:
        raise ValidationError("max_alerts_per_request must be at least 1")
    print(
        f"  settings: env={settings.environment}, "
        f"window={settings.correlation_window_minutes}m, "
        f"rate_limit={settings.rate_limit_per_minute}/min"
    )


def validate_compose() -> None:
    compose_path = ROOT / "docker-compose.yml"
    compose = _read_yaml(compose_path)
    services = compose.get("services")
    if not isinstance(services, dict) or "bamboo11y" not in services:
        raise ValidationError("docker-compose.yml must define a 'bamboo11y' service")
    app = services["bamboo11y"]
    build = app.get("build")
    build_context = build.get("context") if isinstance(build, dict) else build
    if build_context != ".":
        raise ValidationError("compose bamboo11y service must build from the repository root")
    environment = app.get("environment", {})
    if not isinstance(environment, dict):
        raise ValidationError("compose environment must be a mapping")
    required = {
        "BAMBOO11Y_DATABASE_URL",
        "BAMBOO11Y_SERVICE_CATALOG_PATH",
        "BAMBOO11Y_STATIC_DIR",
    }
    missing = sorted(required - set(environment))
    if missing:
        raise ValidationError(f"compose app is missing environment keys: {', '.join(missing)}")
    if not app.get("volumes"):
        raise ValidationError("compose app must mount a persistent data volume")
    if not (ROOT / "Dockerfile").exists():
        raise ValidationError("Dockerfile is missing")

    observability = {
        name: spec
        for name, spec in services.items()
        if isinstance(spec, dict) and "observability" in (spec.get("profiles") or [])
    }
    if {"prometheus", "alertmanager"} - set(observability):
        raise ValidationError(
            "compose must define prometheus and alertmanager observability services"
        )
    mounts = {
        "ops/prometheus/prometheus.yml",
        "ops/prometheus/rules.yml",
        "ops/alertmanager/alertmanager.yml",
    }
    for relative in mounts:
        if not (ROOT / relative).exists():
            raise ValidationError(f"missing observability config: {relative}")
    print(
        "  compose: bamboo11y + " + ", ".join(sorted(observability)) + " (profile: observability)"
    )


def validate_ci() -> None:
    workflow = _read_yaml(ROOT / ".github" / "workflows" / "ci.yml")
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or len(jobs) < 2:
        raise ValidationError("CI workflow must define backend and frontend jobs")
    for job_name in ("backend", "frontend"):
        if job_name not in jobs:
            raise ValidationError(f"CI workflow is missing the '{job_name}' job")
    uses = {
        step.get("uses")
        for job in jobs.values()
        if isinstance(job, dict)
        for step in job.get("steps", [])
        if isinstance(step, dict)
    }
    if not any(value and value.startswith("actions/checkout@") for value in uses):
        raise ValidationError("CI workflow must check out the repository")
    print(f"  ci: jobs={','.join(sorted(jobs))}")


def validate_secret_scan() -> None:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES or path.stat().st_size > 1_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{relative} ({label})")
    if findings:
        raise ValidationError("possible committed secrets: " + ", ".join(sorted(findings)))
    print("  secret scan: no credential-shaped strings found")


def main() -> int:
    print("Validating Bamboo11y configuration")
    checks = [
        ("catalog", validate_catalog),
        ("settings", validate_settings),
        ("compose", validate_compose),
        ("ci", validate_ci),
        ("secrets", validate_secret_scan),
    ]
    try:
        for name, check in checks:
            print(f"- {name}")
            check()
    except ValidationError as exc:
        print(f"\nvalidation failed: {exc}", file=sys.stderr)
        return 1
    print("\nConfiguration is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
