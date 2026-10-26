import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AnswerCard, EmptyState, ErrorState, ExploreMore, LoadingState, MetricTiles, PlayerCard } from "./primitives";

describe("design-system primitives", () => {
  it("AnswerCard exposes its headline as a heading", () => {
    render(<AnswerCard kicker="2024 · NYY · CF" headline="Aaron Judge, 2024: 1.159 OPS" detail="Highest among…" />);
    expect(screen.getByRole("heading", { level: 2, name: "Aaron Judge, 2024: 1.159 OPS" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Answer" })).toHaveTextContent("2024 · NYY · CF");
  });

  it("MetricTiles pairs each label with its value", () => {
    render(<MetricTiles label="Season stats" items={[{ label: "HR", value: "58" }, { label: "AVG", value: ".322" }]} />);
    const terms = screen.getAllByRole("term").map((t) => t.textContent);
    const values = screen.getAllByRole("definition").map((d) => d.textContent);
    expect(terms).toEqual(["HR", "AVG"]);
    expect(values).toEqual(["58", ".322"]);
  });

  it("PlayerCard prints the rank as text, not just a medal colour", () => {
    render(<PlayerCard rank={2} name="Shohei Ohtani" value="240" valueLabel="HR" />);
    const badge = screen.getByText("Rank", { exact: false }).parentElement!;
    expect(badge).toHaveTextContent("Rank 2");
  });

  it("ExploreMore is a native disclosure, closed by default", async () => {
    const user = userEvent.setup();
    render(
      <ExploreMore description="Filters and the full table">
        <p>Advanced content</p>
      </ExploreMore>,
    );
    const details = screen.getByText("Advanced content").closest("details")!;
    expect(details.open).toBe(false);
    await user.click(screen.getByText("Explore more"));
    expect(details.open).toBe(true);
  });

  it("states announce themselves", () => {
    render(
      <>
        <LoadingState label="Loading seasons" />
        <ErrorState title="Data unavailable" />
        <EmptyState title="No seasons match" />
      </>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading seasons");
    expect(screen.getByRole("alert")).toHaveTextContent("Data unavailable");
    expect(screen.getByRole("heading", { name: "No seasons match" })).toBeInTheDocument();
  });
});
