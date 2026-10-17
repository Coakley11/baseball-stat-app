import { describe, expect, it } from "vitest";

import { formatStat, formatYearRange, ordinal } from "./format";

describe("display formatting", () => {
  it("formats rates like the Streamlit pages", () => {
    expect(formatStat(0.311, "rate")).toBe(".311");
    expect(formatStat(1.159, "rate")).toBe("1.159");
    expect(formatStat(0.3, "rate")).toBe(".300");
  });

  it("formats counts and scores", () => {
    expect(formatStat(9718, "count")).toBe("9,718");
    expect(formatStat(954, "score")).toBe("954");
    expect(formatStat(12.25, "score")).toBe("12.3");
  });

  it("shows missing values as a dash, never zero", () => {
    expect(formatStat(null, "count")).toBe("—");
    expect(formatStat(undefined, "rate")).toBe("—");
    expect(formatStat(Number.NaN, "count")).toBe("—");
    expect(formatStat(0, "count")).toBe("0");
  });

  it("formats ranges and ordinals", () => {
    expect(formatYearRange({ start: 2020, end: 2025 })).toBe("2020–2025");
    expect(formatYearRange({ start: 2024, end: 2024 })).toBe("2024");
    expect([1, 2, 3, 4, 11, 12, 13, 21, 112].map(ordinal)).toEqual(["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "112th"]);
  });
});
