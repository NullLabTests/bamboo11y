import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { IncidentList, ServiceCatalog } from "../api/types";
import { SeverityBadge, StatusBadge } from "../components/Badge";
import { PageHeader, Section } from "../components/Layout";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { useResource } from "../hooks/useResource";
import { formatAge, formatDateTime, pluralize } from "../lib/format";

const PAGE_SIZE = 10;

export function IncidentsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [queryDraft, setQueryDraft] = useState({
    base: searchParams.get("q") ?? "",
    value: searchParams.get("q") ?? "",
  });
  const catalog = useResource<ServiceCatalog>("service-catalog-filter", api.services);

  const filters = {
    status: searchParams.get("status") ?? "",
    severity: searchParams.get("severity") ?? "",
    source: searchParams.get("source") ?? "",
    service: searchParams.get("service") ?? "",
    environment: searchParams.get("environment") ?? "",
    active: searchParams.get("active") === "true" ? true : undefined,
    q: searchParams.get("q") ?? "",
    offset: Number(searchParams.get("offset") ?? 0),
  };
  const filterKey = JSON.stringify(filters);
  const incidents = useResource<IncidentList>(`incidents:${filterKey}`, (signal) =>
    api.incidents({ ...filters, limit: PAGE_SIZE }, signal),
  );

  // Derive the draft from the URL instead of syncing it in an effect: if the URL query
  // changes (back/forward), the rendered draft follows it immediately.
  const searchValue = queryDraft.base === filters.q ? queryDraft.value : filters.q;

  function updateFilter(key: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "offset") next.delete("offset");
    setSearchParams(next, { replace: true });
  }

  function clearFilters() {
    setQueryDraft({ base: "", value: "" });
    setSearchParams({}, { replace: true });
  }

  const hasFilters = Boolean(
    filters.status ||
      filters.severity ||
      filters.source ||
      filters.service ||
      filters.environment ||
      filters.active ||
      filters.q,
  );
  const total = incidents.data?.total ?? 0;
  const start = total === 0 ? 0 : filters.offset + 1;
  const end = Math.min(filters.offset + PAGE_SIZE, total);
  const currentPage = Math.floor(filters.offset / PAGE_SIZE) + 1;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="page">
      <PageHeader
        eyebrow="Incident queue"
        title="Grouped signals, ranked for triage"
        description="Filter by lifecycle state, severity, source, or service. Open an incident to inspect the exact rule that grouped each alert, its topology, and nearby changes."
        actions={
          incidents.data ? (
            <span className="queue-count">
              <strong>{incidents.data.active_count}</strong> active · {total} matching
            </span>
          ) : null
        }
      />

      <Section
        title="Filters"
        description="Filters are reflected in the URL so a view can be linked or refreshed without losing context."
      >
        <form
          className="filter-bar"
          onSubmit={(event) => {
            event.preventDefault();
            updateFilter("q", searchValue.trim());
          }}
        >
          <label className="field field--grow">
            <span>Search</span>
            <input
              type="search"
              value={searchValue}
              onChange={(event) =>
                setQueryDraft({ base: filters.q, value: event.target.value })
              }
              placeholder="Incident title or primary service"
            />
          </label>
          <label className="field">
            <span>Status</span>
            <select
              value={filters.status}
              onChange={(event) => updateFilter("status", event.target.value)}
            >
              <option value="">Any status</option>
              <option value="open">Open</option>
              <option value="acknowledged">Acknowledged</option>
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
          <label className="field field--check">
            <input
              type="checkbox"
              checked={Boolean(filters.active)}
              onChange={(event) => updateFilter("active", event.target.checked ? "true" : "")}
            />
            <span>Active only</span>
          </label>
          <div className="filter-bar__actions">
            <button type="submit" className="button button--secondary">
              Apply search
            </button>
            {hasFilters ? (
              <button type="button" className="button button--ghost" onClick={clearFilters}>
                Clear filters
              </button>
            ) : null}
          </div>
        </form>
      </Section>

      <Section
        title="Incidents"
        description="Ordered by most recent update. Severity reflects the highest alert attached to the incident."
        actions={
          total > 0 ? (
            <span className="muted">
              Showing {start}–{end} of {total}
            </span>
          ) : null
        }
      >
        {incidents.loading && !incidents.data ? <LoadingState label="Loading incidents" /> : null}
        {incidents.error ? <ErrorState error={incidents.error} onRetry={incidents.reload} /> : null}
        {incidents.data && incidents.data.items.length === 0 ? (
          <EmptyState
            title={hasFilters ? "No incidents match these filters" : "No incidents yet"}
            copy={
              hasFilters
                ? "Widen the severity or status filter, clear the search, or reset the view."
                : "Send a webhook or run the demo scenario from the overview to create the first incident."
            }
            action={
              hasFilters ? (
                <button type="button" className="button button--secondary" onClick={clearFilters}>
                  Clear filters
                </button>
              ) : (
                <Link className="button button--secondary" to="/">
                  Go to the demo
                </Link>
              )
            }
          />
        ) : null}
        {incidents.data && incidents.data.items.length > 0 ? (
          <>
            <ul className="incident-cards">
              {incidents.data.items.map((incident) => (
                <li key={incident.id}>
                  <Link className="incident-card" to={`/incidents/${incident.id}`}>
                    <div className="incident-card__top">
                      <div className="incident-card__badges">
                        <SeverityBadge severity={incident.severity} />
                        <StatusBadge status={incident.status} />
                        {incident.is_demo ? <span className="demo-tag">demo</span> : null}
                      </div>
                      <span className="incident-card__age">{formatAge(incident.age_seconds)}</span>
                    </div>
                    <h3>{incident.title}</h3>
                    <p className="incident-card__meta">
                      {incident.primary_service} · {incident.environment}
                      {incident.region ? ` · ${incident.region}` : ""}
                    </p>
                    <div className="incident-card__bottom">
                      <span>{pluralize(incident.alert_count, "alert")}</span>
                      <span>{incident.sources.join(" + ")}</span>
                      <span>{pluralize(incident.affected_services.length, "service")}</span>
                      <span>Updated {formatDateTime(incident.updated_at)}</span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
            <div className="pager">
              <button
                type="button"
                className="button button--ghost"
                disabled={filters.offset === 0}
                onClick={() => updateFilter("offset", String(Math.max(0, filters.offset - PAGE_SIZE)))}
              >
                ← Previous
              </button>
              <span className="muted">
                Page {currentPage} of {pageCount}
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
