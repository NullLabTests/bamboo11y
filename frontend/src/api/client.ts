import type {
  AlertList,
  ChangeCreateResponse,
  ChangeKind,
  ChangeList,
  DemoResult,
  IncidentActionResponse,
  IncidentDetail,
  IncidentList,
  IntegrationState,
  NotificationList,
  Overview,
  ServiceCatalog,
  ServiceDetail,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly hints: string[];
  readonly fieldErrors: { field: string; message: string }[];
  readonly requestId: string | null;

  constructor(
    message: string,
    options: {
      status: number;
      code?: string;
      hints?: string[];
      fieldErrors?: { field: string; message: string }[];
      requestId?: string | null;
    },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code ?? "request_failed";
    this.hints = options.hints ?? [];
    this.fieldErrors = options.fieldErrors ?? [];
    this.requestId = options.requestId ?? null;
  }
}

type QueryValue = string | number | boolean | null | undefined;

function withQuery(path: string, params: Record<string, QueryValue> = {}): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }
  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  headers.set("Accept", "application/json");

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(
      "The Bamboo11y API is unreachable. Start the backend and refresh.",
      { status: 0, code: "network_error", hints: ["Run `make dev` or start the API on port 8000."] },
    );
  }

  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text().catch(() => "");

  if (!response.ok) {
    const body = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
    throw new ApiError(
      typeof body.detail === "string" ? body.detail : `Request failed with HTTP ${response.status}.`,
      {
        status: response.status,
        code: typeof body.code === "string" ? body.code : "request_failed",
        hints: Array.isArray(body.hints) ? (body.hints as string[]) : [],
        fieldErrors: Array.isArray(body.errors)
          ? (body.errors as { field: string; message: string }[])
          : [],
        requestId: typeof body.request_id === "string" ? body.request_id : null,
      },
    );
  }

  return payload as T;
}

export interface IncidentFilters {
  status?: string;
  severity?: string;
  source?: string;
  service?: string;
  environment?: string;
  active?: boolean;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface AlertFilters {
  source?: string;
  status?: string;
  severity?: string;
  service?: string;
  environment?: string;
  incident_id?: number;
  limit?: number;
  offset?: number;
}

export interface ChangeFilters {
  service?: string;
  environment?: string;
  limit?: number;
}

export interface CreateChangeInput {
  service: string;
  version: string;
  environment: string;
  region?: string | null;
  kind: ChangeKind;
  summary: string;
  occurred_at?: string | null;
  external_id?: string | null;
}

export const api = {
  overview: (signal?: AbortSignal) => request<Overview>("/api/overview", { signal }),
  incidents: (filters: IncidentFilters = {}, signal?: AbortSignal) =>
    request<IncidentList>(withQuery("/api/incidents", { ...filters }), { signal }),
  incident: (id: number, signal?: AbortSignal) =>
    request<IncidentDetail>(`/api/incidents/${id}`, { signal }),
  updateIncident: (id: number, status: "acknowledged" | "resolved", actor: string, note?: string) =>
    request<IncidentActionResponse>(`/api/incidents/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, actor, note: note?.trim() || null }),
    }),
  alerts: (filters: AlertFilters = {}, signal?: AbortSignal) =>
    request<AlertList>(withQuery("/api/alerts", { ...filters }), { signal }),
  services: (signal?: AbortSignal) => request<ServiceCatalog>("/api/services", { signal }),
  service: (id: string, signal?: AbortSignal) =>
    request<ServiceDetail>(`/api/services/${encodeURIComponent(id)}`, { signal }),
  changes: (filters: ChangeFilters = {}, signal?: AbortSignal) =>
    request<ChangeList>(withQuery("/api/changes", { ...filters }), { signal }),
  createChange: (input: CreateChangeInput) =>
    request<ChangeCreateResponse>("/api/changes", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  integrations: (signal?: AbortSignal) => request<IntegrationState>("/api/integrations", { signal }),
  notifications: (signal?: AbortSignal) =>
    request<NotificationList>("/api/notifications", { signal }),
  dispatchNotifications: () =>
    request<{ attempted: number; sent: number; failed: number }>("/api/notifications/dispatch", {
      method: "POST",
    }),
  runDemo: (fresh = true) =>
    request<DemoResult>("/api/demo/run", {
      method: "POST",
      body: JSON.stringify({ scenario: "payments_degradation", fresh }),
    }),
  resetDemo: () =>
    request<{ deleted: Record<string, number> }>("/api/demo/reset", { method: "POST" }),
};
