import { describe, expect, it } from "vitest";

import { valueAtPath } from "./mapping";

describe("valueAtPath (how a table finds each cell from the API's column field)", () => {
  const row = {
    year: 2024,
    player: { name: "Aaron Judge" },
    bats: null,
    team: null,
    stats: { HR: 58, "2B": 36, SB: null },
  };

  it("follows dotted paths, including stat keys that start with a digit", () => {
    expect(valueAtPath(row, "year")).toBe(2024);
    expect(valueAtPath(row, "player.name")).toBe("Aaron Judge");
    expect(valueAtPath(row, "stats.HR")).toBe(58);
    expect(valueAtPath(row, "stats.2B")).toBe(36);
  });

  it("returns null for anything missing, never a zero or an error", () => {
    expect(valueAtPath(row, "stats.SB")).toBeNull();
    expect(valueAtPath(row, "bats")).toBeNull();
    expect(valueAtPath(row, "team.season_name")).toBeNull(); // team is null
    expect(valueAtPath(row, "stats.WAR")).toBeNull(); // unknown key
    expect(valueAtPath(row, "nope.deeper.still")).toBeNull();
  });

  it("only returns text or numbers; objects are not cells", () => {
    expect(valueAtPath(row, "stats")).toBeNull();
    expect(valueAtPath(row, "player")).toBeNull();
  });
});
