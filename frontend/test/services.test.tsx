import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ServiceDetail } from "../src/api/types";
import {
  checkoutService,
  paymentsService,
  postgresService,
  serviceCatalog,
} from "../test/fixtures";
import { jsonResponse, mockApi, renderRoute } from "../test/render";

const paymentsDetail: ServiceDetail = {
  service: paymentsService,
  upstream: [checkoutService],
  downstream: [postgresService],
  transitive_upstream: [],
  transitive_downstream: [],
  edges: [
    { source: "checkout-api", target: "payments-api" },
    { source: "payments-api", target: "postgres-orders" },
  ],
  recent_changes: [],
};

describe("Services catalog", () => {
  it("opens a catalog entry with direct and transitive context", async () => {
    const user = userEvent.setup();
    mockApi((path) => {
      if (path === "/api/services") return jsonResponse(serviceCatalog);
      if (path === "/api/services/payments-api") return jsonResponse(paymentsDetail);
      return undefined;
    });

    renderRoute("/services");

    expect(await screen.findByRole("heading", { name: "Ownership and dependency context" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Payments API/ }));

    expect(await screen.findByText("Catalog entry")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Payments API" })).toBeInTheDocument();
    const selected = within(screen.getByLabelText("Selected service"));
    expect(selected.getByText("Checkout API")).toBeInTheDocument();
    expect(selected.getByText("Orders PostgreSQL")).toBeInTheDocument();
    expect(selected.getByText("No change events recorded for this service.")).toBeInTheDocument();
    expect(screen.getByText(/reloaded on API restart/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });
});
