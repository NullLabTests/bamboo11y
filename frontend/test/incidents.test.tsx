import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { emptyIncidentList, serviceCatalog } from "../test/fixtures";
import { jsonResponse, mockApi, renderRoute } from "../test/render";

describe("Incident queue", () => {
  it("shows a filter-aware empty state and clears filters", async () => {
    const user = userEvent.setup();
    const requested: string[] = [];
    mockApi((path) => {
      if (path === "/api/services") return jsonResponse(serviceCatalog);
      if (path.startsWith("/api/incidents")) {
        requested.push(path);
        return jsonResponse(emptyIncidentList);
      }
      return undefined;
    });

    renderRoute("/incidents?severity=critical");

    expect(await screen.findByText("No incidents match these filters")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Severity" })).toHaveValue("critical");
    expect(requested.some((path) => path.includes("severity=critical"))).toBe(true);

    await user.click(screen.getAllByRole("button", { name: "Clear filters" })[0]);

    await waitFor(() => {
      const latest = requested.at(-1) ?? "";
      expect(latest).not.toContain("severity=");
    });
    expect(await screen.findByText("No incidents yet")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Severity" })).toHaveValue("");
  });
});
