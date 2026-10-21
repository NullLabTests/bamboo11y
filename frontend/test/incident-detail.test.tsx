import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { incidentDetail } from "../test/fixtures";
import { jsonResponse, mockApi, renderRoute } from "../test/render";

describe("Incident detail", () => {
  it("explains grouping and change context, then acknowledges with an audit event", async () => {
    const user = userEvent.setup();
    let detail = structuredClone(incidentDetail);
    const fetchMock = mockApi((path, init) => {
      if (path === "/api/incidents/7" && (init.method ?? "GET") === "GET") {
        return jsonResponse(detail);
      }
      if (path === "/api/incidents/7/status" && init.method === "PATCH") {
        detail = {
          ...detail,
          incident: {
            ...detail.incident,
            status: "acknowledged",
            acknowledged_at: "2026-10-21T12:00:00Z",
            acknowledged_by: "on-call",
          },
          timeline: [
            ...detail.timeline,
            {
              id: 3,
              event_type: "acknowledged",
              message: "Incident acknowledged by on-call.",
              actor: "on-call",
              automated: false,
              occurred_at: "2026-10-21T12:00:00Z",
              details: { note: null },
            },
          ],
        };
        return jsonResponse({
          incident: detail.incident,
          changed: true,
          notification_dispatched: true,
        });
      }
      return undefined;
    });

    renderRoute("/incidents/7");

    expect(
      await screen.findByRole("heading", { name: "payments-api: Payment authorization failures" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("topology_proximity").length).toBeGreaterThan(0);
    expect(screen.getByText(/direct upstream caller of payments-api/)).toBeInTheDocument();
    expect(screen.getByText(/Checkout success rate dropped/)).toBeInTheDocument();
    expect(screen.getByText("Payments API")).toBeInTheDocument();
    expect(screen.getByText("Checkout API")).toBeInTheDocument();
    expect(screen.getByText("Orders PostgreSQL")).toBeInTheDocument();
    expect(screen.getByText(/v2.14.0/)).toBeInTheDocument();
    expect(screen.getAllByText(/not proof of causation/).length).toBeGreaterThan(0);
    expect(screen.getByText("Incident opened for payments-api in production by the rule-based correlation engine.")).toBeInTheDocument();
    expect(screen.getByText("Alert linked: Checkout error budget is burning")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Acknowledge" }));

    expect(await screen.findByText("Incident acknowledged")).toBeInTheDocument();
    expect((await screen.findAllByText(/by on-call/)).length).toBeGreaterThan(0);
    expect(screen.getByText("Incident acknowledged by on-call.")).toBeInTheDocument();

    const patchCall = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input) === "/api/incidents/7/status" && init?.method === "PATCH",
    );
    expect(patchCall).toBeDefined();
    expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({
      status: "acknowledged",
      actor: "on-call",
      note: null,
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Acknowledge" })).toBeDisabled(),
    );
    expect(screen.getByRole("button", { name: "Resolve incident" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Acknowledge" })).toBeDisabled();
  });
});
