#!/usr/bin/env python3
"""Send realistic alert traffic to a running Bamboo11y instance.

This is a dependency-free operator tool: it uses only the Python standard library and
talks to the same public webhook endpoints that Prometheus Alertmanager or CloudWatch
would use. Unlike the demo endpoint, it does not touch the `is_demo` partition, so it is
safe for exercising a long-running local instance.

Examples:
    python scripts/simulate.py demo
    python scripts/simulate.py prometheus
    python scripts/simulate.py prometheus --status resolved
    python scripts/simulate.py cloudwatch --state ALARM
    python scripts/simulate.py cloudwatch --state OK
    python scripts/simulate.py open-integration --status acknowledged
    python scripts/simulate.py prometheus --repeat 3   # proves idempotency
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 15.0


class SimulatorError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _http_json(
    base_url: str,
    path: str,
    *,
    payload: Any | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, dict[str, Any]]:
    url = f"{base_url.rstrip('/')}{path}"
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SimulatorError(f"Refusing non-HTTP URL: {url}")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - scheme is restricted above.
        url, data=data, method="GET" if data is None else "POST"
    )
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read()
            parsed = json.loads(body) if body else {}
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw.decode("utf-8", errors="replace")}
        raise SimulatorError(
            f"{path} returned HTTP {exc.code}",
            status=exc.code,
            body=parsed,
        ) from exc
    except urllib.error.URLError as exc:
        raise SimulatorError(
            f"Could not reach {url}: {exc.reason}. Is the API running on {base_url}?",
        ) from exc


def _prometheus_payload(
    scenario: str,
    status: str,
    service: str | None,
    environment: str,
    severity: str,
) -> dict[str, Any]:
    now = _now()
    if scenario == "single":
        alerts = [
            _prometheus_alert(
                alert_name="PaymentsAPIHighErrorRate",
                service=service or "payments-api",
                environment=environment,
                severity=severity,
                summary="Payment authorization errors above 5%",
                description=(
                    "The five-minute authorization error rate is 8.4%, above the 5% burn "
                    "threshold. Checkout traffic is beginning to fail."
                ),
                fingerprint="sim-payments-error-rate",
                starts_at=now - timedelta(minutes=6),
                status=status,
            )
        ]
    elif scenario == "unrelated":
        alerts = [
            _prometheus_alert(
                alert_name="SearchLatencyWarning",
                service=service or "search-api",
                environment=environment,
                severity=severity,
                summary="Search p99 latency is elevated",
                description="p99 search latency exceeded 900 ms after a cache TTL change.",
                fingerprint="sim-search-latency",
                starts_at=now - timedelta(minutes=2),
                status=status,
            )
        ]
    else:  # payments: two related services, one group
        alerts = [
            _prometheus_alert(
                alert_name="PaymentsAPIHighErrorRate",
                service=service or "payments-api",
                environment=environment,
                severity=severity,
                summary="Payment authorization errors above 5%",
                description=(
                    "The five-minute authorization error rate is 8.4%, above the 5% burn "
                    "threshold. Checkout traffic is beginning to fail."
                ),
                fingerprint="sim-payments-error-rate",
                starts_at=now - timedelta(minutes=6),
                status=status,
            ),
            _prometheus_alert(
                alert_name="CheckoutErrorBudgetBurn",
                service="checkout-api",
                environment=environment,
                severity="high",
                summary="Checkout 5xx rate is burning the error budget",
                description="Checkout success rate dropped after payment authorization failures.",
                fingerprint="sim-checkout-5xx",
                starts_at=now - timedelta(minutes=5),
                status=status,
            ),
        ]
    return {
        "version": "4",
        "status": status,
        "receiver": "bamboo11y-simulator",
        "groupKey": '{alertname=~"Payments.*|Checkout.*|Search.*"}',
        "truncatedAlerts": 0,
        "alerts": alerts,
    }


def _prometheus_alert(
    *,
    alert_name: str,
    service: str,
    environment: str,
    severity: str,
    summary: str,
    description: str,
    fingerprint: str,
    starts_at: datetime,
    status: str,
) -> dict[str, Any]:
    alert: dict[str, Any] = {
        "status": status,
        "labels": {
            "alertname": alert_name,
            "service": service,
            "environment": environment,
            "region": "us-east-1",
            "severity": severity,
            "cluster": "simulator-use1",
        },
        "annotations": {"summary": summary, "description": description},
        "startsAt": _iso(starts_at),
        "fingerprint": fingerprint,
        "generatorURL": "http://127.0.0.1:9090/graph?g0.expr=simulated",
    }
    if status == "resolved":
        alert["endsAt"] = _iso(_now())
    return alert


def _cloudwatch_payload(
    *,
    state: str,
    service: str,
    environment: str,
    severity: str,
    direct: bool,
) -> dict[str, Any]:
    now = _now()
    alarm_name = f"{service}-p99-latency"
    alarm = {
        "AlarmName": alarm_name,
        "AlarmArn": f"arn:aws:cloudwatch:us-east-1:123456789012:alarm:{alarm_name}",
        "AlarmDescription": f"{service} p99 latency SLO burn.",
        "NewStateValue": state,
        "NewStateReason": (
            f"Threshold crossed: p99 request latency was 2.8 s for three consecutive "
            f"one-minute periods (threshold 1.5 s). State {state}."
        ),
        "StateChangeTime": _iso(now),
        "Region": "us-east-1",
        "AccountId": "123456789012",
        "Namespace": "Bamboo11y/Simulator",
        "Severity": severity,
        "Dimensions": [
            {"Name": "Service", "Value": service},
            {"Name": "Environment", "Value": environment},
        ],
    }
    if direct:
        return alarm
    return {
        "Type": "Notification",
        "MessageId": f"sim-{uuid.uuid4().hex[:16]}",
        "TopicArn": "arn:aws:sns:us-east-1:123456789012:bamboo11y-simulator",
        "Subject": f"ALARM: {alarm_name}" if state == "ALARM" else f"OK: {alarm_name}",
        "Timestamp": _iso(now),
        "Message": json.dumps(alarm),
    }


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _summarize_ingest(status: int, body: dict[str, Any]) -> None:
    print(
        f"HTTP {status} · {body.get('source', 'unknown')} · "
        f"{body.get('received', 0)} received · "
        f"{body.get('created_alerts', 0)} created · "
        f"{body.get('duplicates', 0)} duplicate · "
        f"{body.get('incidents_created', 0)} new incident(s)"
    )
    for outcome in body.get("outcomes", []):
        incident = outcome.get("incident_id")
        suffix = f" -> incident {incident}" if incident else ""
        print(
            f"  {outcome.get('outcome', '?'):<12} "
            f"{outcome.get('service', '?'):<20} "
            f"{outcome.get('environment', '?'):<12} "
            f"{outcome.get('severity', '?'):<8}"
            f"{suffix}"
        )


def run_demo(args: argparse.Namespace) -> int:
    if args.reset:
        status, body = _http_json(args.base_url, "/api/demo/reset", payload={})
        print(f"Reset demo data: HTTP {status}")
        if args.json:
            _print_json(body)
        else:
            print(f"  deleted: {body.get('deleted', {})}")
        print()

    payload = {"scenario": "payments_degradation", "fresh": not args.keep_existing}
    status, body = _http_json(args.base_url, "/api/demo/run", payload=payload)
    if args.json:
        _print_json(body)
        return 0

    summary = body.get("summary", {})
    print(f"HTTP {status} · scenario {body.get('scenario')} · run {body.get('run_id')}")
    print(
        f"  {body.get('alerts_received')} received · "
        f"{body.get('unique_alerts')} unique · "
        f"{body.get('duplicate_deliveries')} duplicate · "
        f"{body.get('notifications_delivered')} notification(s)"
    )
    print(f"  primary incident: {body.get('primary_incident_id')}")
    print(
        f"  primary alerts: {summary.get('primary_incident_alert_count')} across "
        f"{', '.join(summary.get('primary_incident_sources', []))}"
    )
    change = summary.get("nearby_change", {})
    print(
        f"  nearby change: {change.get('service')} {change.get('version')} "
        f"{change.get('minutes_before_first_alert')} min before first alert "
        f"({change.get('relationship')})"
    )
    print(f"  unrelated incidents preserved: {summary.get('unrelated_incident_count')}")
    for incident in body.get("incidents", []):
        print(
            f"    #{incident.get('id')} {incident.get('severity'):<8} "
            f"{incident.get('primary_service'):<20} {incident.get('alert_count')} alert(s) "
            f"{incident.get('sources')}"
        )
    print(f"  dashboard: {args.base_url.rstrip('/')}/incidents/{body.get('primary_incident_id')}")
    print(f"  disclaimer: {summary.get('disclaimer')}")
    return 0


def run_prometheus(args: argparse.Namespace) -> int:
    payload = _prometheus_payload(
        args.scenario, args.status, args.service, args.environment, args.severity
    )
    if args.dry_run:
        _print_json(payload)
        return 0
    for attempt in range(1, args.repeat + 1):
        delivery_id = f"sim-am-{uuid.uuid4().hex[:12]}"
        status, body = _http_json(
            args.base_url,
            "/api/webhooks/alerts/prometheus",
            payload=payload,
            headers={"X-Bamboo11y-Delivery-Id": delivery_id},
        )
        print(f"[{attempt}/{args.repeat}] delivery {delivery_id}")
        if args.json:
            _print_json(body)
        else:
            _summarize_ingest(status, body)
        if attempt < args.repeat:
            _sleep(args.interval)
    return 0


def run_cloudwatch(args: argparse.Namespace) -> int:
    payload = _cloudwatch_payload(
        state=args.state,
        service=args.service,
        environment=args.environment,
        severity=args.severity,
        direct=args.direct,
    )
    if args.dry_run:
        _print_json(payload)
        return 0
    for attempt in range(1, args.repeat + 1):
        delivery_id = f"sim-cw-{uuid.uuid4().hex[:12]}"
        status, body = _http_json(
            args.base_url,
            "/api/webhooks/alerts/cloudwatch",
            payload=payload,
            headers={"X-Bamboo11y-Delivery-Id": delivery_id},
        )
        print(f"[{attempt}/{args.repeat}] delivery {delivery_id}")
        if args.json:
            _print_json(body)
        else:
            _summarize_ingest(status, body)
        if attempt < args.repeat:
            _sleep(args.interval)
    return 0


def _open_integration_payload(
    *,
    app: str,
    check: str,
    status: str,
    environment: str,
    subject: str | None,
    description: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "app": app,
        "check": check,
        "status": status,
        "timestamp": _iso(_now()),
        "tags": {
            "environment": environment,
            "region": "us-east-1",
            "source": "bamboo11y-simulator",
        },
    }
    if subject:
        payload["subject"] = subject
    if description:
        payload["description"] = description
    return payload


def run_open_integration(args: argparse.Namespace) -> int:
    subject = f"{args.app} {args.check} {args.status}"
    description = (
        f"Open-integration event: {args.app}/{args.check} reported {args.status}. "
        "Vendor-neutral payload contract for any monitoring system."
    )
    payload = _open_integration_payload(
        app=args.app,
        check=args.check,
        status=args.status,
        environment=args.environment,
        subject=subject,
        description=description,
    )
    if args.dry_run:
        _print_json(payload)
        return 0
    for attempt in range(1, args.repeat + 1):
        delivery_id = f"sim-oi-{uuid.uuid4().hex[:12]}"
        status, body = _http_json(
            args.base_url,
            "/api/webhooks/alerts/open-integration",
            payload=payload,
            headers={"X-Bamboo11y-Delivery-Id": delivery_id},
        )
        print(f"[{attempt}/{args.repeat}] delivery {delivery_id}")
        if args.json:
            _print_json(body)
        else:
            _summarize_ingest(status, body)
        if attempt < args.repeat:
            _sleep(args.interval)
    return 0


def run_reset(args: argparse.Namespace) -> int:
    status, body = _http_json(args.base_url, "/api/demo/reset", payload={})
    print(f"HTTP {status}")
    if args.json:
        _print_json(body)
    else:
        print(f"  deleted: {body.get('deleted', {})}")
    return 0


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simulate.py",
        description=(
            "Send local, realistic alert traffic to Bamboo11y. Never contacts a real "
            "Prometheus, CloudWatch, or Slack service."
        ),
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Bamboo11y API base URL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="run the deterministic demo scenario")
    demo.add_argument("--reset", action="store_true", help="reset demo data before running")
    demo.add_argument(
        "--keep-existing",
        action="store_true",
        help="do not reset demo data as part of the run (may duplicate the scenario)",
    )
    demo.add_argument("--json", action="store_true", help="print the raw JSON response")
    demo.set_defaults(handler=run_demo)

    prometheus = subparsers.add_parser(
        "prometheus", aliases=["alertmanager"], help="send an Alertmanager webhook"
    )
    prometheus.add_argument(
        "--scenario", choices=("payments", "single", "unrelated"), default="payments"
    )
    prometheus.add_argument("--status", choices=("firing", "resolved"), default="firing")
    prometheus.add_argument("--service", help="override the primary service label")
    prometheus.add_argument("--environment", default="production")
    prometheus.add_argument(
        "--severity", choices=("critical", "high", "medium", "low", "info"), default="critical"
    )
    prometheus.add_argument(
        "--repeat", type=int, default=1, help="repeat the delivery to prove idempotency"
    )
    prometheus.add_argument("--interval", type=float, default=0.5, help="seconds between repeats")
    prometheus.add_argument("--dry-run", action="store_true", help="print the payload only")
    prometheus.add_argument("--json", action="store_true", help="print raw responses")
    prometheus.set_defaults(handler=run_prometheus)

    cloudwatch = subparsers.add_parser("cloudwatch", help="send a CloudWatch/SNS webhook")
    cloudwatch.add_argument(
        "--state", choices=("ALARM", "OK", "INSUFFICIENT_DATA"), default="ALARM"
    )
    cloudwatch.add_argument("--service", default="payments-api")
    cloudwatch.add_argument("--environment", default="production")
    cloudwatch.add_argument(
        "--severity", choices=("critical", "high", "medium", "low", "info"), default="high"
    )
    cloudwatch.add_argument(
        "--direct", action="store_true", help="send the alarm object without SNS"
    )
    cloudwatch.add_argument(
        "--repeat", type=int, default=1, help="repeat the delivery to prove idempotency"
    )
    cloudwatch.add_argument("--interval", type=float, default=0.5, help="seconds between repeats")
    cloudwatch.add_argument("--dry-run", action="store_true", help="print the payload only")
    cloudwatch.add_argument("--json", action="store_true", help="print raw responses")
    cloudwatch.set_defaults(handler=run_cloudwatch)

    open_integration = subparsers.add_parser(
        "open-integration",
        aliases=["oim"],
        help="send a vendor-neutral app/check event (open-integration contract)",
    )
    open_integration.add_argument("--app", default="checkout")
    open_integration.add_argument("--check", default="sessions-pool")
    open_integration.add_argument(
        "--status", choices=("critical", "warning", "acknowledged", "ok"), default="critical"
    )
    open_integration.add_argument("--environment", default="production")
    open_integration.add_argument(
        "--repeat", type=int, default=1, help="repeat the delivery to prove idempotency"
    )
    open_integration.add_argument(
        "--interval", type=float, default=0.5, help="seconds between repeats"
    )
    open_integration.add_argument("--dry-run", action="store_true", help="print the payload only")
    open_integration.add_argument("--json", action="store_true", help="print raw responses")
    open_integration.set_defaults(handler=run_open_integration)

    reset = subparsers.add_parser("reset", help="clear demo-partition data only")
    reset.add_argument("--json", action="store_true", help="print the raw JSON response")
    reset.set_defaults(handler=run_reset)

    for command in (demo, prometheus, cloudwatch, reset):
        command.add_argument(
            "--base-url",
            default=argparse.SUPPRESS,
            help="Bamboo11y API base URL (also accepted before the subcommand)",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "repeat", 1) < 1:
        parser.error("--repeat must be at least 1")
    if getattr(args, "interval", 0) < 0:
        parser.error("--interval cannot be negative")
    try:
        return int(args.handler(args))
    except SimulatorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if exc.body:
            print(json.dumps(exc.body, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
