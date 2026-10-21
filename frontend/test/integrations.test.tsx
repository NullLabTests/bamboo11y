import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { integrationState, serviceCatalog } from "../test/fixtures";
import { errorResponse, jsonResponse, mockApi, renderRoute } from "../test/render";

describe("Integrations", () => {
  it("records a change event and explains that it is context only", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi((path, init) => {
      if (path === "/api/integrations") return jsonResponse(integrationState);
      if (path === "/api/services") return jsonResponse(serviceCatalog);
      if (path === "/api/changes" && init.method === "POST") {
        return jsonResponse(
          {
            item: {
              id: 9,
              service: "payments-api",
              version: "v9.1.0",
              environment: "production",
              region: null,
              kind: "deployment",
              summary: "Canary rollout of the checkout retry policy.",
              occurred_at: "2026-10-21T12:00:00Z",
              source: "bamboo11y-api",
              is_demo: false,
            },
            created: true,
          },
          201,
        );
      }
      return undefined;
    });

    renderRoute("/integrations");

    expect(await screen.findByText("/api/webhooks/alerts/cloudwatch")).toBeInTheDocument();
    expect(screen.getByText("/api/webhooks/alerts/prometheus")).toBeInTheDocument();
    expect(screen.getByText("SHA-256(source + '|' + deduplication_key)")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Version / identifier"), "v9.1.0");
    await user.type(
      screen.getByLabelText("Summary"),
      "Canary rollout of the checkout retry policy.",
    );
    await user.click(screen.getByRole("button", { name: "Record change" }));

    expect(
      await screen.findByText(
        "Change recorded for payments-api v9.1.0. It is now eligible as temporal context, not as a root cause.",
      ),
    ).toBeInTheDocument();

    const call = fetchMock.mock.calls.find(
      ([input, init]) => String(input) === "/api/changes" && init?.method === "POST",
    );
    expect(call).toBeDefined();
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      service: "payments-api",
      environment: "production",
      version: "v9.1.0",
      kind: "deployment",
      external_id: null,
      occurred_at: null,
    });
  });

  it("surfaces field errors returned by the API", async () => {
    const user = userEvent.setup();
    mockApi((path, init) => {
      if (path === "/api/integrations") return jsonResponse(integrationState);
      if (path === "/api/services") return jsonResponse(serviceCatalog);
      if (path === "/api/changes" && init.method === "POST") {
        return errorResponse(422, {
          detail: "Request validation failed",
          code: "validation_error",
          errors: [{ field: "version", message: "String should have at least 1 character" }],
        });
      }
      return undefined;
    });

    renderRoute("/integrations");
    await screen.findByText("/api/webhooks/alerts/cloudwatch");

    await user.type(screen.getByLabelText("Version / identifier"), "v1");
    await user.type(screen.getByLabelText("Summary"), "Deploy");
    await user.click(screen.getByRole("button", { name: "Record change" }));

    expect(await screen.findByText("Request validation failed")).toBeInTheDocument();
    expect(
      screen.getByText("version: String should have at least 1 character"),
    ).toBeInTheDocument();
  });
});
