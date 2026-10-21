import { screen } from "@testing-library/react";

import { jsonResponse, mockApi, renderRoute } from "../test/render";
import { emptyOverview } from "../test/fixtures";

describe("Overview page", () => {
  it("renders the empty dashboard from real zero-valued API data", async () => {
    mockApi((path) => {
      if (path === "/api/overview") return jsonResponse(emptyOverview);
      return undefined;
    });

    renderRoute("/");

    expect(
      await screen.findByRole("heading", { name: "What needs attention now" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("No active incidents")).toBeInTheDocument();
    expect(screen.getByText("No change events")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run demo scenario" })).toBeInTheDocument();
    expect(screen.getByText("AWS CloudWatch")).toBeInTheDocument();
    expect(screen.getByText("Prometheus Alertmanager")).toBeInTheDocument();
    expect(screen.getAllByText("No alerts received yet")).toHaveLength(2);
    expect(screen.getByText("No acknowledgements yet")).toBeInTheDocument();
    expect(screen.getByText(/Snapshot generated/)).toBeInTheDocument();
  });
});
