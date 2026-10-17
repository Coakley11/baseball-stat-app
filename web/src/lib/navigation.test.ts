import { describe, expect, it } from "vitest";

import { activeNavItem, NAV_ITEMS, NAV_SECTIONS } from "./navigation";

describe("navigation map", () => {
  it("keeps the accepted U1 section order", () => {
    expect(NAV_SECTIONS.map((s) => s.label)).toEqual(["Home", "Players", "Insights", "Draft", "My League", "Account"]);
  });

  it("lists every current page exactly once", () => {
    const keys = NAV_ITEMS.map((i) => i.streamlitKey);
    expect(new Set(keys).size).toBe(keys.length);
    // Mirrors nav_groups.NAV_SECTIONS in the Streamlit app: Home + 17 pages.
    expect(keys).toHaveLength(18);
    expect(new Set(NAV_ITEMS.map((i) => i.href)).size).toBe(NAV_ITEMS.length);
  });

  it("marks only the WEB-M1 pages as ready", () => {
    expect(NAV_ITEMS.filter((i) => i.status === "ready").map((i) => i.label)).toEqual([
      "Home",
      "Historical Explorer",
      "Leaderboards",
    ]);
  });

  it("finds the active page from the pathname", () => {
    expect(activeNavItem("/")?.id).toBe("home");
    expect(activeNavItem("/players/historical")?.id).toBe("historical");
    expect(activeNavItem("/players/leaderboards/")?.id).toBe("leaderboards");
    expect(activeNavItem("/players/career")).toBeUndefined();
  });
});
