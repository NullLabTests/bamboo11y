import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { IncidentDetail } from "../api/types";
import { SeverityBadge, StatusBadge } from "../components/Badge";
import { ErrorState, LoadingState } from "../components/States";
import { TopologyView } from "../components/TopologyView";
import { useToast } from "../components/toast-context";
import { useResource } from "../hooks/useResource";
import {
  asSourceLabel,
  formatAge,
  formatDateTime,
  formatMinutes,
  titleCase,
} from "../lib/format";

function stringDetail(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function DetailBody({
  detail,
  onChanged,
}: {
  detail: IncidentDetail;
  onChanged: () => void;
}) {
  const { incident } = detail;
  const [actor, setActor] = useState("on-call");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"acknowledged" | "resolved" | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const { notify } = useToast();

  async function act(status: "acknowledged" | "resolved") {
    setBusy(status);
    setActionError(null);
    try {
      const result = await api.updateIncident(incident.id, status, actor, note);
      if (result.changed) {
        notify(`Incident ${result.incident.status}`, {
          detail: result.notification_dispatched
            ? "The lifecycle event was added to the outbox and delivered to the local mock channel."
            : "The lifecycle event was recorded; no notification delivery was needed.",
          tone: "success",
        });
        setNote("");
      } else {
        notify("No change was recorded", {
          detail: "This action was already applied, so no duplicate event or notification was created.",
        });
      }
      onChanged();
    } catch (cause) {
      const apiError =
        cause instanceof ApiError
          ? cause
          : new ApiError("The lifecycle action failed.", { status: 0 });
      setActionError(apiError);
      notify("Lifecycle action failed", { detail: apiError.message, tone: "error" });
    } finally {
      setBusy(null);
    }
  }

  const canAcknowledge = incident.status === "open";
  const canResolve = incident.status !== "resolved";

  return (
    <>
      <div className="detail-heading">
        <Link className="back-link" to="/incidents">
          ← Incident queue
        </Link>
        <div className="detail-heading__badges">
          <SeverityBadge severity={incident.severity} />
          <StatusBadge status={incident.status} />
          {incident.is_demo ? <span className="demo-tag">demo data</span> : null}
        </div>
        <h1>{incident.title}</h1>
        <p className="detail-heading__meta">
          {incident.primary_service} · {incident.environment}
          {incident.region ? ` · ${incident.region}` : ""} · opened{" "}
          {formatDateTime(incident.created_at)} · age {formatAge(incident.age_seconds)}
        </p>
      </div>

      <div className="detail-stats">
        <div>
          <span>Alerts</span>
          <strong>{incident.alert_count}</strong>
        </div>
        <div>
          <span>Sources</span>
          <strong>{incident.sources.map(asSourceLabel).join(" + ")}</strong>
        </div>
        <div>
          <span>Affected services</span>
          <strong>{incident.affected_services.join(", ")}</strong>
        </div>
        <div>
          <span>First alert</span>
          <strong>{formatDateTime(incident.first_alert_at)}</strong>
        </div>
        <div>
          <span>Last alert</span>
          <strong>{formatDateTime(incident.last_alert_at)}</strong>
        </div>
      </div>

      <div className="detail-grid">
        <div className="detail-main">
          <section className="panel" aria-labelledby="lifecycle-title">
            <div className="panel__header">
              <div>
                <h2 id="lifecycle-title">Lifecycle</h2>
                <p className="panel__description">
                  Human actions are append-only events. Repeating an action creates no duplicate
                  event or notification.
                </p>
              </div>
            </div>
            <div className="lifecycle">
              <div className="lifecycle__facts">
                <p>
                  <span>Acknowledged</span>
                  {incident.acknowledged_at
                    ? `${formatDateTime(incident.acknowledged_at)} by ${incident.acknowledged_by}`
                    : "Not yet"}
                </p>
                <p>
                  <span>Resolved</span>
                  {incident.resolved_at
                    ? `${formatDateTime(incident.resolved_at)} by ${incident.resolved_by}`
                    : "Not yet"}
                </p>
                {incident.resolution_note ? (
                  <p className="lifecycle__note">
                    <span>Resolution note</span>
                    {incident.resolution_note}
                  </p>
                ) : null}
              </div>
              <div className="lifecycle__form">
                <label className="field">
                  <span>Actor</span>
                  <input
                    value={actor}
                    maxLength={128}
                    onChange={(event) => setActor(event.target.value)}
                    placeholder="Your name"
                  />
                </label>
                <label className="field">
                  <span>Note (optional)</span>
                  <textarea
                    value={note}
                    maxLength={2000}
                    rows={2}
                    onChange={(event) => setNote(event.target.value)}
                    placeholder="What did you check or change?"
                  />
                </label>
                <div className="lifecycle__actions">
                  <button
                    type="button"
                    className="button button--secondary"
                    disabled={!canAcknowledge || busy !== null}
                    onClick={() => act("acknowledged")}
                  >
                    {busy === "acknowledged" ? "Acknowledging…" : "Acknowledge"}
                  </button>
                  <button
                    type="button"
                    className="button button--primary"
                    disabled={!canResolve || busy !== null}
                    onClick={() => act("resolved")}
                  >
                    {busy === "resolved" ? "Resolving…" : "Resolve incident"}
                  </button>
                </div>
                {!canAcknowledge && incident.status === "acknowledged" ? (
                  <p className="muted">Acknowledged incidents can be resolved, not re-acknowledged.</p>
                ) : null}
                {!canResolve ? (
                  <p className="muted">
                    This incident is resolved. A matching source re-fire may reopen it
                    automatically; manual reopening is intentionally not exposed.
                  </p>
                ) : null}
                {actionError ? (
                  <p className="inline-error" role="alert">
                    {actionError.message}
                  </p>
                ) : null}
              </div>
            </div>
          </section>

          <section className="panel" aria-labelledby="timeline-title">
            <div className="panel__header">
              <div>
                <h2 id="timeline-title">Audit timeline</h2>
                <p className="panel__description">
                  Correlation, source updates, and operator actions in event order.
                </p>
              </div>
            </div>
            <ol className="timeline">
              {detail.timeline.map((event) => {
                const eventNote = stringDetail(event.details.note);
                return (
                  <li key={event.id} className="timeline__item">
                    <span
                      className={`timeline__marker timeline__marker--${event.automated ? "auto" : "human"}`}
                      aria-hidden="true"
                    />
                    <div className="timeline__body">
                      <div className="timeline__top">
                        <span className="timeline__type">{titleCase(event.event_type)}</span>
                        <span className="muted">{formatDateTime(event.occurred_at)}</span>
                      </div>
                      <p>{event.message}</p>
                      <div className="timeline__meta">
                        <span className={event.automated ? "actor-tag" : "actor-tag actor-tag--human"}>
                          {event.automated ? "automation" : event.actor ?? "operator"}
                        </span>
                        {eventNote ? <span>{eventNote}</span> : null}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>

          <section className="panel" aria-labelledby="alerts-title">
            <div className="panel__header">
              <div>
                <h2 id="alerts-title">Alerts and grouping reasons</h2>
                <p className="panel__description">
                  The rule and facts that placed each alert in this incident.
                </p>
              </div>
            </div>
            <ul className="alert-cards">
              {detail.alerts.map((alert) => (
                <li key={alert.id} className="alert-card">
                  <div className="alert-card__top">
                    <div className="alert-card__badges">
                      <SeverityBadge severity={alert.severity} />
                      <StatusBadge status={alert.status} />
                      <span className="source-tag">{asSourceLabel(alert.source)}</span>
                      {alert.occurrences > 1 ? (
                        <span className="occurrence-tag">{alert.occurrences} deliveries</span>
                      ) : null}
                    </div>
                    <span className="muted">{formatDateTime(alert.occurred_at)}</span>
                  </div>
                  <h3>{alert.title}</h3>
                  <p className="muted">
                    {alert.service} · {alert.environment}
                    {alert.region ? ` · ${alert.region}` : ""}
                  </p>
                  <p>{alert.description}</p>
                  {alert.correlation ? (
                    <details className="reason" open>
                      <summary>
                        Why this alert is here
                        <span className="reason__rule">{alert.correlation.rule}</span>
                      </summary>
                      <p className="reason__summary">{alert.correlation.summary}</p>
                      <div className="reason__facts">
                        {alert.correlation.matched_on?.map((fact) => (
                          <span className="fact-chip" key={fact}>
                            {fact.replaceAll("_", " ")}
                          </span>
                        ))}
                      </div>
                      {alert.correlation.note ? (
                        <p className="reason__note">{alert.correlation.note}</p>
                      ) : null}
                    </details>
                  ) : null}
                  <p className="alert-card__fingerprint">
                    fingerprint <code>{alert.fingerprint.slice(0, 24)}…</code> · dedupe key{" "}
                    <code>{alert.dedupe_key.length > 40 ? `${alert.dedupe_key.slice(0, 40)}…` : alert.dedupe_key}</code>
                  </p>
                </li>
              ))}
            </ul>
          </section>
        </div>

        <aside className="detail-side">
          <section className="panel" aria-labelledby="topology-title">
            <div className="panel__header">
              <div>
                <h2 id="topology-title">Topology context</h2>
                <p className="panel__description">
                  Ownership and dependency context from the checked-in catalog.
                </p>
              </div>
            </div>
            <TopologyView topology={detail.topology} />
          </section>

          <section className="panel" aria-labelledby="changes-title">
            <div className="panel__header">
              <div>
                <h2 id="changes-title">Nearby changes</h2>
                <p className="panel__description">
                  Within ±{detail.change_context.window_minutes} minutes of the alert span.
                </p>
              </div>
            </div>
            {detail.nearby_changes.length === 0 ? (
              <p className="muted">
                No deployment or config change was recorded for affected services in this window.
              </p>
            ) : (
              <ul className="nearby-changes">
                {detail.nearby_changes.map((change) => (
                  <li key={change.id}>
                    <div className="nearby-changes__top">
                      <span className="context-tag">temporal context only</span>
                      <span className="muted">
                        {change.relation === "before_first_alert" ? "before" : "after"} first alert
                      </span>
                    </div>
                    <p className="nearby-changes__title">
                      {change.service} <code>{change.version}</code>
                    </p>
                    <p className="nearby-changes__when">
                      {formatMinutes(change.minutes_from_first_alert)} from first alert ·{" "}
                      {titleCase(change.kind)}
                    </p>
                    <p>{change.summary}</p>
                    <p className="nearby-changes__disclaimer">{change.disclaimer}</p>
                  </li>
                ))}
              </ul>
            )}
            <p className="context-note context-note--compact">
              <span className="context-note__label">Guardrail</span>
              <span>{detail.change_context.disclaimer}</span>
            </p>
          </section>

          <section className="panel" aria-labelledby="notifications-title">
            <div className="panel__header">
              <div>
                <h2 id="notifications-title">Notification outbox</h2>
                <p className="panel__description">
                  One event-scoped message per lifecycle transition.
                </p>
              </div>
            </div>
            {detail.notifications.length === 0 ? (
              <p className="muted">No notifications were enqueued for this incident.</p>
            ) : (
              <ul className="outbox">
                {detail.notifications.map((notification) => (
                  <li key={notification.id}>
                    <div>
                      <p className="outbox__event">{titleCase(notification.event_type)}</p>
                      <p className="muted">
                        {notification.channel} · {formatDateTime(notification.sent_at ?? notification.created_at)}
                      </p>
                    </div>
                    <span className={`outbox__status outbox__status--${notification.status}`}>
                      {notification.status}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
      </div>
    </>
  );
}

export function IncidentDetailPage() {
  const params = useParams();
  const parsed = Number(params.incidentId);
  const incidentId = Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
  const resource = useResource<IncidentDetail>(`incident:${incidentId}`, (signal) =>
    api.incident(incidentId, signal),
  );

  if (!incidentId) {
    return (
      <div className="page">
        <ErrorState
          error={
            new ApiError("That incident identifier is not valid.", {
              status: 400,
              code: "invalid_incident_id",
              hints: ["Open an incident from the queue instead of editing the URL."],
            })
          }
        />
      </div>
    );
  }

  return (
    <div className="page detail-page">
      {resource.loading && !resource.data ? <LoadingState label="Loading incident context" /> : null}
      {resource.error ? <ErrorState error={resource.error} onRetry={resource.reload} /> : null}
      {resource.data ? (
        <DetailBody detail={resource.data} onChanged={resource.reload} />
      ) : null}
    </div>
  );
}
