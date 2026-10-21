import { useMemo, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ChangeKind, IntegrationState, ServiceCatalog } from "../api/types";
import { PageHeader, Section } from "../components/Layout";
import { ErrorState, LoadingState } from "../components/States";
import { useToast } from "../components/toast-context";
import { useResource } from "../hooks/useResource";
import { asSourceLabel, formatDateTime, titleCase } from "../lib/format";

interface FormState {
  service: string;
  environment: string;
  version: string;
  kind: ChangeKind;
  summary: string;
  occurred_at: string;
  external_id: string;
}

function IntegrationBody({
  data,
  catalog,
  onRefresh,
}: {
  data: IntegrationState;
  catalog: ServiceCatalog | null;
  onRefresh: () => void;
}) {
  const { notify } = useToast();
  const [dispatchBusy, setDispatchBusy] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [submitBusy, setSubmitBusy] = useState(false);
  const [formError, setFormError] = useState<ApiError | null>(null);
  const [formMessage, setFormMessage] = useState<string | null>(null);

  const defaultService = catalog?.services[0];
  const [form, setForm] = useState<FormState>({
    service: "payments-api",
    environment: "production",
    version: "",
    kind: "deployment",
    summary: "",
    occurred_at: "",
    external_id: "",
  });

  const selectedService = useMemo(
    () => catalog?.services.find((service) => service.id === form.service) ?? defaultService,
    [catalog, defaultService, form.service],
  );
  const environments = selectedService?.environments ?? ["production", "staging"];

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(text);
      notify("Endpoint copied to clipboard", { tone: "success" });
      window.setTimeout(() => setCopied(null), 2500);
    } catch {
      notify("Clipboard access is unavailable", {
        detail: "Select the endpoint text and copy it manually.",
        tone: "error",
      });
    }
  }

  async function dispatch() {
    setDispatchBusy(true);
    try {
      const result = await api.dispatchNotifications();
      notify("Outbox dispatch complete", {
        detail: `${result.sent} sent, ${result.failed} failed, ${result.attempted} attempted.`,
        tone: result.failed > 0 ? "error" : "success",
      });
      onRefresh();
    } catch (cause) {
      notify("Could not dispatch the outbox", {
        detail: cause instanceof Error ? cause.message : "Unknown error",
        tone: "error",
      });
    } finally {
      setDispatchBusy(false);
    }
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setFormMessage(null);
    setSubmitBusy(true);
    try {
      const response = await api.createChange({
        service: form.service,
        environment: form.environment,
        version: form.version.trim(),
        kind: form.kind,
        summary: form.summary.trim(),
        occurred_at: form.occurred_at ? new Date(form.occurred_at).toISOString() : null,
        external_id: form.external_id.trim() || null,
      });
      setFormMessage(
        response.created
          ? `Change recorded for ${response.item.service} ${response.item.version}. It is now eligible as temporal context, not as a root cause.`
          : "This external ID was already recorded. The existing event was returned; no duplicate was created.",
      );
      notify(response.created ? "Change event recorded" : "Change event already existed", {
        detail: `${response.item.service} ${response.item.version} · ${response.item.environment}`,
        tone: "success",
      });
      onRefresh();
    } catch (cause) {
      const apiError =
        cause instanceof ApiError
          ? cause
          : new ApiError("The change event could not be recorded.", { status: 0 });
      setFormError(apiError);
    } finally {
      setSubmitBusy(false);
    }
  }

  function updateService(serviceId: string) {
    const service = catalog?.services.find((item) => item.id === serviceId);
    setForm((current) => ({
      ...current,
      service: serviceId,
      environment: service?.environments.includes(current.environment)
        ? current.environment
        : (service?.environments[0] ?? current.environment),
    }));
  }

  return (
    <>
      <div className="integration-grid">
        {data.sources.map((source) => (
          <section className="panel integration-card" key={source.source} aria-labelledby={`${source.source}-title`}>
            <div className="panel__header">
              <div>
                <h2 id={`${source.source}-title`}>{source.display_name}</h2>
                <p className="panel__description">{source.description}</p>
              </div>
              <span className="badge badge--status-receiving">
                <span className="badge__dot" aria-hidden="true" />
                {source.alerts_24h} / 24h
              </span>
            </div>
            <div className="endpoint-row">
              <code>{source.endpoint}</code>
              <button
                type="button"
                className="button button--ghost button--small"
                onClick={() => copy(source.endpoint)}
              >
                {copied === source.endpoint ? "Copied" : "Copy"}
              </button>
            </div>
            <p className="muted">
              {source.last_received_at
                ? `Last alert ${formatDateTime(source.last_received_at)}`
                : "No alerts received in this environment yet."}
            </p>
            <p className="endpoint-note">
              Verified by the same adapter and ingestion service used by the demo scenario.
            </p>
          </section>
        ))}

        <section className="panel integration-card" aria-labelledby="notifications-title">
          <div className="panel__header">
            <div>
              <h2 id="notifications-title">Notifications</h2>
              <p className="panel__description">
                {data.notifications.external_webhook_configured
                  ? "External webhook configured."
                  : "Local mock Slack sink; no external account or credential used."}
              </p>
            </div>
            <span className="badge badge--neutral">{data.notifications.channel}</span>
          </div>
          <div className="notification-counts">
            <div>
              <span>Sent</span>
              <strong>{data.notifications.counts.sent}</strong>
            </div>
            <div>
              <span>Pending</span>
              <strong>{data.notifications.counts.pending}</strong>
            </div>
            <div>
              <span>Failed</span>
              <strong>{data.notifications.counts.failed}</strong>
            </div>
          </div>
          <p className="muted">{data.notifications.local_sink_note}</p>
          <button
            type="button"
            className="button button--secondary"
            onClick={dispatch}
            disabled={dispatchBusy}
          >
            {dispatchBusy ? "Dispatching…" : "Dispatch pending outbox"}
          </button>
          {data.notifications.recent.length > 0 ? (
            <ul className="outbox outbox--compact">
              {data.notifications.recent.slice(0, 4).map((notification) => (
                <li key={notification.id}>
                  <div>
                    <p className="outbox__event">{titleCase(notification.event_type)}</p>
                    <p className="muted">
                      incident #{notification.incident_id} ·{" "}
                      {formatDateTime(notification.sent_at ?? notification.created_at)}
                    </p>
                  </div>
                  <span className={`outbox__status outbox__status--${notification.status}`}>
                    {notification.status}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      </div>

      <div className="integration-grid integration-grid--text">
        <Section title="Rate limiting" description="Applied before webhook parsing.">
          <dl className="definition-list">
            <div>
              <dt>Budget</dt>
              <dd>{data.rate_limit.requests_per_minute} requests / minute</dd>
            </div>
            <div>
              <dt>Scope</dt>
              <dd>{data.rate_limit.scope}</dd>
            </div>
            <div>
              <dt>Production note</dt>
              <dd>{data.rate_limit.note}</dd>
            </div>
          </dl>
        </Section>
        <Section title="Idempotency" description="Fingerprints, not delivery metadata, define identity.">
          <dl className="definition-list">
            <div>
              <dt>Strategy</dt>
              <dd>
                <code>{data.idempotency.strategy}</code>
              </dd>
            </div>
            <div>
              <dt>Duplicate behavior</dt>
              <dd>{data.idempotency.duplicate_behavior}</dd>
            </div>
            <div>
              <dt>Delivery metadata</dt>
              <dd>{data.idempotency.delivery_header}</dd>
            </div>
          </dl>
        </Section>
      </div>

      <Section
        title="Record a change event"
        description="Deployments, config changes, rollbacks, and feature flags become temporal context near incidents. They are never labelled as the root cause."
      >
        <form className="change-form" onSubmit={submit}>
          <label className="field">
            <span>Service</span>
            <select value={form.service} onChange={(event) => updateService(event.target.value)}>
              {(catalog?.services ?? []).map((service) => (
                <option key={service.id} value={service.id}>
                  {service.name}
                </option>
              ))}
              {!catalog ? <option value={form.service}>{form.service}</option> : null}
            </select>
          </label>
          <label className="field">
            <span>Environment</span>
            <select
              value={form.environment}
              onChange={(event) => setForm({ ...form, environment: event.target.value })}
            >
              {environments.map((environment) => (
                <option key={environment} value={environment}>
                  {environment}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Kind</span>
            <select
              value={form.kind}
              onChange={(event) => setForm({ ...form, kind: event.target.value as ChangeKind })}
            >
              <option value="deployment">Deployment</option>
              <option value="config">Config</option>
              <option value="rollback">Rollback</option>
              <option value="feature_flag">Feature flag</option>
            </select>
          </label>
          <label className="field">
            <span>Version / identifier</span>
            <input
              required
              maxLength={64}
              value={form.version}
              onChange={(event) => setForm({ ...form, version: event.target.value })}
              placeholder="v2.15.0"
            />
          </label>
          <label className="field field--wide">
            <span>Summary</span>
            <input
              required
              minLength={3}
              maxLength={600}
              value={form.summary}
              onChange={(event) => setForm({ ...form, summary: event.target.value })}
              placeholder="Canary rollout of the retry-budget refactor."
            />
          </label>
          <label className="field">
            <span>Occurred at (optional)</span>
            <input
              type="datetime-local"
              value={form.occurred_at}
              onChange={(event) => setForm({ ...form, occurred_at: event.target.value })}
            />
          </label>
          <label className="field">
            <span>External ID (optional)</span>
            <input
              maxLength={128}
              value={form.external_id}
              onChange={(event) => setForm({ ...form, external_id: event.target.value })}
              placeholder="deploy-2026-10-21-42"
            />
          </label>
          <div className="change-form__actions">
            <button type="submit" className="button button--primary" disabled={submitBusy}>
              {submitBusy ? "Recording…" : "Record change"}
            </button>
            <span className="muted">Occurred time defaults to now when omitted.</span>
          </div>
          {formMessage ? (
            <p className="form-success" role="status">
              {formMessage}
            </p>
          ) : null}
          {formError ? (
            <div className="inline-error" role="alert">
              <strong>{formError.message}</strong>
              {formError.fieldErrors.map((error) => (
                <span key={`${error.field}-${error.message}`}>
                  {error.field}: {error.message}
                </span>
              ))}
              {formError.hints.map((hint) => (
                <span key={hint}>{hint}</span>
              ))}
            </div>
          ) : null}
        </form>
      </Section>

      <Section
        title="Local mock receiver"
        description="A credential-free endpoint for exercising the optional HTTP notification path."
      >
        <div className="endpoint-row">
          <code>{data.mock_slack_endpoint}</code>
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={() => copy(data.mock_slack_endpoint)}
          >
            {copied === data.mock_slack_endpoint ? "Copied" : "Copy"}
          </button>
        </div>
        <p className="muted">
          The outbox remains the source of truth for deliveries. This receiver acknowledges a
          payload and intentionally does not replay or render it.
        </p>
      </Section>
    </>
  );
}

export function IntegrationsPage() {
  const integrations = useResource<IntegrationState>("integrations", api.integrations);
  const catalog = useResource<ServiceCatalog>("service-catalog-changes", api.services);

  return (
    <div className="page">
      <PageHeader
        eyebrow="Integrations"
        title="Ingestion, delivery, and change context"
        description="Inspect the actual source wiring, copy endpoints, review rate-limit and idempotency behavior, and record the change events that give incidents their temporal context."
        actions={
          <button
            type="button"
            className="button button--secondary"
            onClick={() => {
              integrations.reload();
              catalog.reload();
            }}
          >
            Refresh state
          </button>
        }
      />
      {integrations.loading && !integrations.data ? (
        <LoadingState label="Loading integration state" />
      ) : null}
      {integrations.error ? (
        <ErrorState error={integrations.error} onRetry={integrations.reload} />
      ) : null}
      {integrations.data ? (
        <IntegrationBody
          data={integrations.data}
          catalog={catalog.data}
          onRefresh={integrations.reload}
        />
      ) : null}
      {integrations.data ? (
        <p className="source-note">
          Endpoints are documented as Alertmanager, CloudWatch/SNS, and open-integration
          app/check webhooks. {asSourceLabel("prometheus")}, {asSourceLabel("cloudwatch")}, and{" "}
          {asSourceLabel("open-integration")} are the enabled adapters in this build; the
          open-integration contract follows the vendor-neutral pattern documented by BigPanda
          (see{" "}
          <a href="https://github.com/NullLabTests/bamboo11y/blob/main/docs/inspirations.md">
            docs/inspirations.md
          </a>
          ). Bamboo11y is not affiliated with BigPanda.
        </p>
      ) : null}
    </div>
  );
}
