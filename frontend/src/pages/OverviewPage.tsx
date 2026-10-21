import { Link } from "react-router-dom";

import type { Overview, Severity } from "../api/types";
import { api } from "../api/client";
import { AlertVolumeChart } from "../components/AlertVolumeChart";
import { DemoPanel } from "../components/DemoPanel";
import { PageHeader, Section } from "../components/Layout";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { SeverityBadge, StatusBadge } from "../components/Badge";
import { useResource } from "../hooks/useResource";
import { formatAge, formatDateTime, formatDuration, titleCase } from "../lib/format";

const severityOrder: Severity[] = ["critical", "high", "medium", "low", "info"];

function Metric({
  label,
  value,
  hint,
  to,
}: {
  label: string;
  value: number | string;
  hint: string;
  to?: string;
}) {
  const body = (
    <>
      <p className="metric__label">{label}</p>
      <p className="metric__value">{value}</p>
      <p className="metric__hint">{hint}</p>
    </>
  );
  return to ? (
    <Link className="metric card-link" to={to}>
      {body}
    </Link>
  ) : (
    <div className="metric">{body}</div>
  );
}

function SeverityMix({ mix }: { mix: Record<Severity, number> }) {
  const total = severityOrder.reduce((sum, severity) => sum + (mix[severity] ?? 0), 0);
  return (
    <div className="severity-mix">
      <div className="severity-mix__bar" aria-hidden="true">
        {total === 0 ? (
          <span className="severity-mix__empty" />
        ) : (
          severityOrder.map((severity) =>
            mix[severity] ? (
              <span
                key={severity}
                className={`severity-mix__segment severity-fill--${severity}`}
                style={{ flexGrow: mix[severity] }}
              />
            ) : null,
          )
        )}
      </div>
      <ul className="severity-mix__legend">
        {severityOrder.map((severity) => (
          <li key={severity}>
            <span className={`legend-dot severity-fill--${severity}`} aria-hidden="true" />
            <span>{titleCase(severity)}</span>
            <strong>{mix[severity] ?? 0}</strong>
          </li>
        ))}
      </ul>
      <p className="muted">
        {total === 0
          ? "No active incidents, so there is no severity mix to report."
          : `${total} active ${total === 1 ? "incident" : "incidents"}, counted at their highest alert severity.`}
      </p>
    </div>
  );
}

function OverviewBody({ data }: { data: Overview }) {
  const mtta = data.metrics.mean_time_to_acknowledge_seconds;
  return (
    <>
      <div className="metrics-grid">
        <Metric
          label="Active incidents"
          value={data.metrics.active_incidents}
          hint="Open or acknowledged"
          to="/incidents?active=true"
        />
        <Metric
          label="Alerts · 24h"
          value={data.metrics.alerts_last_24h}
          hint="Normalized across sources"
          to="/signals"
        />
        <Metric
          label="Affected services"
          value={data.metrics.affected_services}
          hint="Distinct services in active incidents"
          to="/services"
        />
        <Metric
          label="Mean time to acknowledge"
          value={mtta === null ? "—" : formatDuration(mtta)}
          hint={mtta === null ? "No acknowledgements yet" : "From incident creation"}
        />
        <Metric
          label="Catalog coverage"
          value={data.metrics.service_count}
          hint="Services with ownership context"
          to="/services"
        />
      </div>

      <div className="overview-grid">
        <Section
          title="Alert volume"
          description="Receipt-time buckets across both webhook formats."
          className="overview-grid__wide"
        >
          <AlertVolumeChart buckets={data.alert_volume} />
        </Section>

        <Section title="Severity mix" description="Active incidents by peak severity.">
          <SeverityMix mix={data.severity_mix} />
        </Section>

        <Section
          title="Recent incidents"
          description="Ordered by last update. Every row links to its evidence."
          className="overview-grid__wide"
          actions={
            <Link className="text-link" to="/incidents">
              All incidents →
            </Link>
          }
        >
          {data.recent_incidents.length === 0 ? (
            <EmptyState
              title="No active incidents"
              copy="The store is quiet. Run the deterministic demo above to inject a realistic two-source alert storm."
            />
          ) : (
            <ul className="incident-rows">
              {data.recent_incidents.map((incident) => (
                <li key={incident.id}>
                  <Link
                    to={`/incidents/${incident.id}`}
                    className="incident-row incident-row--overview"
                  >
                    <SeverityBadge severity={incident.severity} />
                    <span className="incident-row__stack">
                      <span className="incident-row__title">{incident.title}</span>
                      <span className="incident-row__meta">
                        {incident.primary_service} · {incident.environment} ·{" "}
                        {incident.alert_count} alerts · {incident.sources.join(" + ")}
                      </span>
                    </span>
                    <StatusBadge status={incident.status} />
                    <span className="incident-row__age">{formatAge(incident.age_seconds)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Source health" description="Last 24 hours, derived from ingested alerts.">
          <ul className="source-list">
            {data.source_health.map((source) => (
              <li key={source.source}>
                <div>
                  <p className="source-list__name">{source.display_name}</p>
                  <p className="muted">
                    {source.last_received_at
                      ? `Last alert ${formatDateTime(source.last_received_at)}`
                      : "No alerts received yet"}
                  </p>
                </div>
                <div className="source-list__count">
                  <span className={source.status === "receiving" ? "pulse" : "pulse pulse--idle"} />
                  <span>{source.alerts_24h} alerts</span>
                  <span className="source-list__status">{source.status}</span>
                </div>
              </li>
            ))}
          </ul>
        </Section>

        <Section
          title="Recent changes"
          description="Deployments and config changes are context, never proof of cause."
          actions={
            <Link className="text-link" to="/integrations">
              Record a change →
            </Link>
          }
        >
          {data.recent_changes.length === 0 ? (
            <EmptyState
              title="No change events"
              copy="Record a deployment from the integrations page, or run the demo to create one."
            />
          ) : (
            <ul className="change-list">
              {data.recent_changes.map((change) => (
                <li key={change.id}>
                  <div className="change-list__main">
                    <span className="change-kind">{titleCase(change.kind)}</span>
                    <span>
                      {change.service} <code>{change.version}</code>
                    </span>
                  </div>
                  <p className="muted">{change.summary}</p>
                  <p className="change-list__meta">
                    {formatDateTime(change.occurred_at)} · {change.environment} · temporal
                    context only
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
    </>
  );
}

export function OverviewPage() {
  const overview = useResource<Overview>("overview", api.overview);

  return (
    <div className="page">
      <PageHeader
        eyebrow="Command center"
        title="What needs attention now"
        description="A calm view over alerts from both monitoring sources, the services they touch, and the changes nearby. Every number is computed from the local incident store."
        actions={
          <Link className="button button--secondary" to="/signals">
            Inspect signal stream
          </Link>
        }
      />
      <DemoPanel onCompleted={overview.reload} />
      {overview.loading && !overview.data ? <LoadingState label="Loading overview" /> : null}
      {overview.error ? <ErrorState error={overview.error} onRetry={overview.reload} /> : null}
      {overview.data ? <OverviewBody data={overview.data} /> : null}
      {overview.data ? (
        <p className="generated-note">Snapshot generated {formatDateTime(overview.data.generated_at)}</p>
      ) : null}
    </div>
  );
}
