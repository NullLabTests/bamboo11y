import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { DemoResult } from "../api/types";
import { useToast } from "./toast-context";

export function DemoPanel({ onCompleted }: { onCompleted?: () => void }) {
  const [result, setResult] = useState<DemoResult | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [resetting, setResetting] = useState(false);
  const { notify } = useToast();

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const demo = await api.runDemo(true);
      setResult(demo);
      notify("Demo scenario complete", {
        detail: `${demo.unique_alerts} unique alerts grouped into ${demo.incidents.length} incidents.`,
        tone: "success",
      });
      onCompleted?.();
    } catch (cause) {
      const apiError =
        cause instanceof ApiError ? cause : new ApiError("The demo could not run.", { status: 0 });
      setError(apiError);
      notify("Demo scenario failed", { detail: apiError.message, tone: "error" });
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setResetting(true);
    try {
      const response = await api.resetDemo();
      setResult(null);
      notify("Demo data cleared", {
        detail: `${response.deleted.incidents ?? 0} incidents and ${response.deleted.alerts ?? 0} alerts removed. Live data was not touched.`,
        tone: "success",
      });
      onCompleted?.();
    } catch (cause) {
      const apiError =
        cause instanceof ApiError ? cause : new ApiError("The demo reset failed.", { status: 0 });
      notify("Could not reset demo data", { detail: apiError.message, tone: "error" });
    } finally {
      setResetting(false);
    }
  }

  return (
    <section className="demo-panel" aria-labelledby="demo-title">
      <div className="demo-panel__intro">
        <p className="eyebrow">Deterministic scenario</p>
        <h2 id="demo-title">Payments degradation, end to end</h2>
        <p>
          Send six webhook deliveries from two monitoring formats through the real ingestion
          pipeline. Watch normalization, fingerprint deduplication, topology-aware correlation,
          a nearby deployment, and mock notifications resolve into a three-incident picture.
        </p>
        <ul className="demo-panel__list">
          <li>1 duplicate delivery suppressed without a second notification</li>
          <li>3 related alerts from Prometheus and CloudWatch in one incident</li>
          <li>2 unrelated incidents kept separate</li>
          <li>1 deployment shown as temporal context only</li>
        </ul>
        <div className="demo-panel__actions">
          <button type="button" className="button button--primary" onClick={run} disabled={busy}>
            {busy ? "Running scenario…" : result ? "Run scenario again" : "Run demo scenario"}
          </button>
          {result ? (
            <button
              type="button"
              className="button button--ghost"
              onClick={reset}
              disabled={resetting}
            >
              {resetting ? "Clearing…" : "Reset demo data"}
            </button>
          ) : null}
        </div>
        {error ? (
          <div className="inline-error" role="alert">
            <strong>{error.message}</strong>
            {error.hints.length > 0 ? <span>{error.hints[0]}</span> : null}
          </div>
        ) : null}
      </div>
      <div className="demo-panel__result" aria-live="polite">
        {result ? (
          <>
            <div className="demo-result__header">
              <span className="demo-result__eyebrow">Scenario result</span>
              <code>{result.run_id}</code>
            </div>
            <p className="demo-result__headline">{result.summary.headline}</p>
            <dl className="demo-stats">
              <div>
                <dt>Deliveries</dt>
                <dd>{result.alerts_received}</dd>
              </div>
              <div>
                <dt>Unique alerts</dt>
                <dd>{result.unique_alerts}</dd>
              </div>
              <div>
                <dt>Duplicates</dt>
                <dd>{result.duplicate_deliveries}</dd>
              </div>
              <div>
                <dt>Incidents</dt>
                <dd>{result.incidents.length}</dd>
              </div>
              <div>
                <dt>Notifications</dt>
                <dd>{result.notifications_delivered}</dd>
              </div>
            </dl>
            {result.primary_incident_id ? (
              <Link className="button button--secondary" to={`/incidents/${result.primary_incident_id}`}>
                Open primary incident →
              </Link>
            ) : null}
            <div className="context-note">
              <span className="context-note__label">Context only</span>
              <p>
                {result.summary.nearby_change.service} {result.summary.nearby_change.version} was
                recorded {result.summary.nearby_change.minutes_before_first_alert} minutes before
                the first alert. {result.summary.disclaimer}
              </p>
            </div>
            <ul className="demo-incidents">
              {result.incidents.map((incident) => (
                <li key={incident.id}>
                  <Link to={`/incidents/${incident.id}`}>{incident.title}</Link>
                  <span>
                    {incident.alert_count} alerts · {incident.environment}
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <div className="demo-panel__placeholder">
            <span className="demo-orbit" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
            <p>
              The result panel shows persisted counts, not staged animation. Every alert,
              incident, timeline event, and notification below is queryable through the API.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
