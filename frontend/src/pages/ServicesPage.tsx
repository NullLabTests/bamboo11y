import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { ServiceCatalog, ServiceDetail } from "../api/types";
import { TierBadge } from "../components/Badge";
import { PageHeader, Section } from "../components/Layout";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { TopologyView } from "../components/TopologyView";
import { useResource } from "../hooks/useResource";
import { formatDateTime, pluralize, titleCase } from "../lib/format";

function ServiceDetailPanel({
  serviceId,
  onClose,
}: {
  serviceId: string;
  onClose: () => void;
}) {
  const detail = useResource<ServiceDetail>(`service:${serviceId}`, (signal) =>
    api.service(serviceId, signal),
  );

  if (detail.loading && !detail.data) return <LoadingState label={`Loading ${serviceId}`} />;
  if (detail.error) return <ErrorState error={detail.error} onRetry={detail.reload} />;
  if (!detail.data) return null;

  const { service } = detail.data;
  return (
    <div className="service-detail">
      <div className="service-detail__heading">
        <div>
          <p className="eyebrow">Catalog entry</p>
          <h2>{service.name}</h2>
          <p className="muted">
            {service.id} · {service.owner} · {service.team}
          </p>
        </div>
        <div className="service-detail__actions">
          <TierBadge tier={service.tier} />
          <button type="button" className="button button--ghost" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
      <p>{service.description}</p>
      <div className="service-facts">
        <div>
          <span>Environments</span>
          <strong>{service.environments.join(", ")}</strong>
        </div>
        <div>
          <span>Repository</span>
          <strong>{service.repository ?? "Not recorded"}</strong>
        </div>
        <div>
          <span>Runbook</span>
          <strong>{service.runbook ?? "Not recorded"}</strong>
        </div>
      </div>

      <TopologyView
        topology={{
          focus_service: service,
          service_found: true,
          owner: service.owner,
          team: service.team,
          tier: service.tier,
          affected_services: [service.id],
          upstream: detail.data.upstream,
          downstream: detail.data.downstream,
          transitive_upstream: detail.data.transitive_upstream,
          transitive_downstream: detail.data.transitive_downstream,
          edges: detail.data.edges,
          catalog_version: 1,
          disclaimer:
            "Dependencies are catalog facts for triage context. They do not prove that one service caused another service's symptoms.",
        }}
      />

      <div className="service-detail__grid">
        <div>
          <h3>Transitive callers</h3>
          {detail.data.transitive_upstream.length === 0 ? (
            <p className="muted">No transitive callers within three hops.</p>
          ) : (
            <ul className="path-list">
              {detail.data.transitive_upstream.map((item) => (
                <li key={`${item.service.id}-${item.depth}`}>
                  <span>{item.service.name}</span>
                  <code>{item.path.join(" → ")}</code>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3>Transitive dependencies</h3>
          {detail.data.transitive_downstream.length === 0 ? (
            <p className="muted">No transitive dependencies within three hops.</p>
          ) : (
            <ul className="path-list">
              {detail.data.transitive_downstream.map((item) => (
                <li key={`${item.service.id}-${item.depth}`}>
                  <span>{item.service.name}</span>
                  <code>{item.path.join(" → ")}</code>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <h3>Recent changes</h3>
      {detail.data.recent_changes.length === 0 ? (
        <p className="muted">No change events recorded for this service.</p>
      ) : (
        <ul className="change-list">
          {detail.data.recent_changes.map((change) => (
            <li key={change.id}>
              <div className="change-list__main">
                <span className="change-kind">{titleCase(change.kind)}</span>
                <span>
                  <code>{change.version}</code> · {change.environment}
                </span>
              </div>
              <p className="muted">{change.summary}</p>
              <p className="change-list__meta">
                {formatDateTime(change.occurred_at)} · {change.source}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ServicesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const catalog = useResource<ServiceCatalog>("services", api.services);
  const selected = searchParams.get("service");

  const services = (catalog.data?.services ?? []).filter((service) => {
    const needle = query.trim().toLowerCase();
    if (!needle) return true;
    return [service.id, service.name, service.owner, service.team]
      .join(" ")
      .toLowerCase()
      .includes(needle);
  });

  function select(serviceId: string) {
    const next = new URLSearchParams(searchParams);
    next.set("service", serviceId);
    setSearchParams(next, { replace: true });
  }

  function close() {
    const next = new URLSearchParams(searchParams);
    next.delete("service");
    setSearchParams(next, { replace: true });
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="Service catalog"
        title="Ownership and dependency context"
        description="The catalog is a checked-in source of truth for owners, tiers, environments, and one-hop dependencies. It is editable in config/services.yaml and reloaded on API restart."
        actions={
          catalog.data ? (
            <span className="queue-count">
              <strong>{catalog.data.services.length}</strong> services ·{" "}
              {pluralize(catalog.data.edges.length, "edge")}
            </span>
          ) : null
        }
      />

      {catalog.loading && !catalog.data ? <LoadingState label="Loading service catalog" /> : null}
      {catalog.error ? <ErrorState error={catalog.error} onRetry={catalog.reload} /> : null}

      {catalog.data ? (
        <div className={selected ? "catalog-layout catalog-layout--detail" : "catalog-layout"}>
          <div className="catalog-main">
            <Section
              title="Services"
              description="Critical-tier services are listed first by the API."
              actions={
                <label className="field field--inline">
                  <span className="visually-hidden">Search services</span>
                  <input
                    type="search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search name, owner, or team"
                  />
                </label>
              }
            >
              {services.length === 0 ? (
                <EmptyState
                  title="No services match"
                  copy="Try a different name, owner, or team."
                  action={
                    <button type="button" className="button button--secondary" onClick={() => setQuery("")}>
                      Clear search
                    </button>
                  }
                />
              ) : (
                <ul className="service-grid">
                  {services.map((service) => (
                    <li key={service.id}>
                      <button
                        type="button"
                        className={
                          selected === service.id ? "service-card is-selected" : "service-card"
                        }
                        onClick={() => select(service.id)}
                        aria-pressed={selected === service.id}
                      >
                        <div className="service-card__top">
                          <span className="service-card__name">{service.name}</span>
                          <TierBadge tier={service.tier} />
                        </div>
                        <span className="service-card__id">{service.id}</span>
                        <span className="service-card__owner">{service.owner}</span>
                        <p>{service.description}</p>
                        <div className="service-card__meta">
                          <span>{pluralize(service.depends_on.length, "dependency", "dependencies")}</span>
                          <span>{pluralize(service.dependents.length, "caller")}</span>
                          <span>{service.environments.join(" · ")}</span>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </div>
          {selected ? (
            <aside className="catalog-side panel" aria-label="Selected service">
              <ServiceDetailPanel serviceId={selected} onClose={close} />
            </aside>
          ) : (
            <aside className="catalog-side catalog-side--hint">
              <div className="panel catalog-hint">
                <p className="eyebrow">Reading the graph</p>
                <h2>Select a service</h2>
                <p>
                  Open any catalog entry to see direct callers, dependencies, transitive paths, and
                  recent change events. Dependency edges explain blast-radius context; they do not
                  assert cause.
                </p>
                <p className="muted">
                  Edit <code>config/services.yaml</code>, then restart the API to reload ownership
                  and topology everywhere.
                </p>
              </div>
            </aside>
          )}
        </div>
      ) : null}
    </div>
  );
}
