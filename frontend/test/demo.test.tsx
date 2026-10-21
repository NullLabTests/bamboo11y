import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { demoResult, emptyOverview } from "../test/fixtures";
import { errorResponse, jsonResponse, mockApi, renderRoute } from "../test/render";

describe("Demo scenario", () => {
  it("runs the scenario, renders persisted counts, and links to the primary incident", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi((path, init) => {
      if (path === "/api/overview") return jsonResponse(emptyOverview);
      if (path === "/api/demo/run" && init.method === "POST") {
        return jsonResponse(demoResult, 201);
      }
      return undefined;
    });

    renderRoute("/");
    await user.click(await screen.findByRole("button", { name: "Run demo scenario" }));

    expect(await screen.findByText("Scenario result")).toBeInTheDocument();
    expect(screen.getByText("abc123def456")).toBeInTheDocument();
    expect(screen.getByText(/6 minutes before the first alert/)).toBeInTheDocument();
    expect(screen.getByText(/does not prove that it caused the incident/)).toBeInTheDocument();

    const primaryLink = screen.getByRole("link", { name: "Open primary incident →" });
    expect(primaryLink).toHaveAttribute("href", "/incidents/42");

    const uniqueStat = screen.getByText("Unique alerts").closest("div");
    expect(uniqueStat).toHaveTextContent("5");

    expect(screen.getByText("payments-api: Payment authorization errors above 5%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset demo data" })).toBeInTheDocument();

    const demoCall = fetchMock.mock.calls.find(([input]) => String(input).includes("/api/demo/run"));
    expect(demoCall).toBeDefined();
    expect(JSON.parse(String(demoCall?.[1]?.body))).toEqual({
      scenario: "payments_degradation",
      fresh: true,
    });
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([input]) => String(input) === "/api/overview").length,
      ).toBeGreaterThan(1),
    );
  });

  it("shows a useful error when the scenario cannot run", async () => {
    const user = userEvent.setup();
    mockApi((path, init) => {
      if (path === "/api/overview") return jsonResponse(emptyOverview);
      if (path === "/api/demo/run" && init.method === "POST") {
        return errorResponse(500, {
          detail: "Scenario execution failed safely.",
          code: "internal_error",
          hints: ["Inspect the server log by request ID."],
        });
      }
      return undefined;
    });

    renderRoute("/");
    await user.click(await screen.findByRole("button", { name: "Run demo scenario" }));

    expect(await screen.findAllByText("Scenario execution failed safely.")).not.toHaveLength(0);
    expect(screen.getByText("Inspect the server log by request ID.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run demo scenario" })).toBeEnabled();
  });
});
