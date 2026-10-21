import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { AlertList, ServiceCatalog } from "../api/types";
import { SeverityBadge, StatusBadge } from "../components/Badge";
import { PageHeader, Section } from "../components/Layout";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { useResource } from "../hooks/useResource";
import { asSourceLabel, formatDateTime, pluralize, shortFingerprint } from "../lib/format";

const PAGE_SIZE = 25;

export function SignalsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const catalog = useResource<ServiceCatalog>("service-catalog-signals", api.services);

  const filters = {
    source: searchParams.get("source") ?? "",
    status: searchParams.get("status") ?? "",
    severity: searchParams.get("severity") ?? "",
    service: searchParams.get("service") ?? "",
    environment: searchParams.get("environment") ?? "",
    offset: Number(searchParams.get("offset") ?? 0),
  };

  const alerts = useResource<AlertList>(`alerts:${JSON.stringify(filters)}`, (signal) =>
    api.alerts({ ...filters, limit: PAGE_SIZE }, signal),
  );

  function updateFilter(key: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "offset") next.delete("offset");
    setSearchParams(next, { replace: true });
  }

  const hasFilters = Boolean(
    filters.source || filters.status || filters.severity || filters.service || filters.environment,
  );
  const total = alerts.data?.total ?? 0;
  const end = Math.min(filters.offset + PAGE_SIZE, total);
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="page">
      <PageHeader
        eyebrow="Signal stream"
        title="Every normalized alert"
        description="Both source formats resolve to one contract. Duplicate deliveries increment an occurrence counter instead of creating another alert."
        actions={
          alerts.data ? (
            <span className="queue-count">
              <strong>{total}</strong> matching alerts
            </span>
          ) : null
        }
      />

      <Section title="Filters" description="Source-specific payloads share one query surface.">
        <div className="filter-bar">
          <label className="field">
            <span>Source</span>
            <select
              value={filters.source}
              onChange={(event) => updateFilter("source", event.target.value)}
            >
              <option value="">Any source</option>
              <option value="prometheus">Prometheus</option>
              <option value="cloudwatch">CloudWatch</option>
              <option value="open-integration">Open Integration</option>
            </select>
          </label>
          <label className="field">
            <span>Status</span>
            <select
              value={filters.status}
              onChange={(event) => updateFilter("status", event.target.value)}
            >
              <option value="">Any status</option>
              <option value="firing">Firing</option>
              <option value="resolved">Resolved</option>
            </select>
          </label>
          <label className="field">
            <span>Severity</span>
            <select
              value={filters.severity}
              onChange={(event) => updateFilter("severity", event.target.value)}
            >
              <option value="">Any severity</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
              <option value="info">Info</option>
            </select>
          </label>
          <label className="field">
            <span>Service</span>
            <select
              value={filters.service}
              onChange={(event) => updateFilter("service", event.target.value)}
            >
              <option value="">Any service</option>
              {(catalog.data?.services ?? []).map((service) => (
                <option key={service.id} value={service.id}>
                  {service.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Environment</span>
            <select
              value={filters.environment}
              onChange={(event) => updateFilter("environment", event.target.value)}
            >
              <option value="">Any environment</option>
              {(catalog.data?.environments ?? ["production", "staging"]).map((environment) => (
                <option key={environment} value={environment}>
                  {environment}
                </option>
              ))}
            </select>
          </label>
          {hasFilters ? (
            <div className="filter-bar__actions">
              <button
                type="button"
                className="button button--ghost"
                onClick={() => setSearchParams({}, { replace: true })}
              >
                Clear filters
              </button>
            </div>
          ) : null}
        </div>
      </Section>

      <Section
        title="Alerts"
        description="Event time comes from the source when present; receipt time is the fallback."
        actions={total > 0 ? <span className="muted">{total} total</span> : null}
      >
        {alerts.loading && !alerts.data ? <LoadingState label="Loading alert stream" /> : null}
        {alerts.error ? <ErrorState error={alerts.error} onRetry={alerts.reload} /> : null}
        {alerts.data && alerts.data.items.length === 0 ? (
          <EmptyState
            title={hasFilters ? "No alerts match these filters" : "No alerts received"}
            copy={
              hasFilters
                ? "Clear a filter or widen the severity selection."
                : "POST an Alertmanager, CloudWatch, or open-integration payload to /api/webhooks/alerts/prometheus, /cloudwatch, or /open-integration — or run the demo."
            }
            action={
              hasFilters ? (
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => setSearchParams({}, { replace: true })}
                >
                  Clear filters
                </button>
              ) : (
                <Link className="button button--secondary" to="/">
                  Run the demo
                </Link>
              )
            }
          />
        ) : null}
        {alerts.data && alerts.data.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table className="data-table">
                <caption className="visually-hidden">
                  Normalized alerts with source, severity, status, occurrence count, and linked
                  incident.
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Alert</th>
                    <th scope="col">Source</th>
                    <th scope="col">Severity</th>
                    <th scope="col">Status</th>
                    <th scope="col">Deliveries</th>
                    <th scope="col">Event time</th>
                    <th scope="col">Incident</th>
                  </tr>
                </thead>
                <tbody>
                  {alerts.data.items.map((alert) => (
                    <tr key={alert.id}>
                      <td>
                        <div className="table-primary">{alert.title}</div>
                        <div className="table-secondary">
                          {alert.service} · {alert.environment}
                          {alert.region ? ` · ${alert.region}` : ""}
                        </div>
                        <div className="table-code">
                          {alert.dedupe_key.length > 48
                            ? `${alert.dedupe_key.slice(0, 48)}…`
                            : alert.dedupe_key}
                        </div>
                      </td>
                      <td>{asSourceLabel(alert.source)}</td>
                      <td>
                        <SeverityBadge severity={alert.severity} />
                      </td>
                      <td>
                        <StatusBadge status={alert.status} />
                      </td>
                      <td>
                        <span className="occurrence-count">
                          {alert.occurrences} {alert.occurrences === 1 ? "delivery" : "deliveries"}
                        </span>
                        <div className="table-code" title={alert.fingerprint}>
                          {shortFingerprint(alert.fingerprint)}
                        </div>
                      </td>
                      <td className="table-nowrap">{formatDateTime(alert.occurred_at)}</td>
                      <td>
                        {alert.incident_id ? (
                          <Link className="text-link" to={`/incidents/${alert.incident_id}`}>
                            #{alert.incident_id}
                          </Link>
                        ) : (
                          <span className="muted">unlinked</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pager">
              <button
                type="button"
                className="button button--ghost"
                disabled={filters.offset === 0}
                onClick={() =>
                  updateFilter("offset", String(Math.max(0, filters.offset - PAGE_SIZE)))
                }
              >
                ← Previous
              </button>
              <span className="muted">
                Page {Math.floor(filters.offset / PAGE_SIZE) + 1} of {pageCount} ·{" "}
                {pluralize(Math.max(0, end - filters.offset), "alert")}
              </span>
              <button
                type="button"
                className="button button--ghost"
                disabled={end >= total}
                onClick={() => updateFilter("offset", String(filters.offset + PAGE_SIZE))}
              >
                Next →
              </button>
            </div>
          </>
        ) : null}
      </Section>
    </div>
  );
}
