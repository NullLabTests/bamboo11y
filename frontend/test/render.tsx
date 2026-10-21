import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactElement } from "react";
import { vi } from "vitest";

import { AppRoutes } from "../src/App";
import { ToastProvider } from "../src/components/Toast";

export function renderRoute(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ToastProvider>
        <AppRoutes />
      </ToastProvider>
    </MemoryRouter>,
  );
}

export function renderWithProviders(element: ReactElement) {
  return render(
    <MemoryRouter>
      <ToastProvider>{element}</ToastProvider>
    </MemoryRouter>,
  );
}

export type FetchHandler = (
  path: string,
  init: RequestInit,
) => Response | Promise<Response> | undefined;

export function mockApi(handler: FetchHandler) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = new URL(raw, "http://bamboo11y.local").pathname;
    const query = new URL(raw, "http://bamboo11y.local").search;
    const response = await handler(`${path}${query}`, init);
    if (!response) {
      throw new Error(`Unhandled API request: ${init.method ?? "GET"} ${path}${query}`);
    }
    return response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function errorResponse(
  status: number,
  body: { detail: string; code: string; hints?: string[]; errors?: { field: string; message: string }[] },
): Response {
  return jsonResponse(
    {
      detail: body.detail,
      code: body.code,
      request_id: "req-test",
      errors: body.errors ?? [],
      hints: body.hints ?? [],
    },
    status,
  );
}
