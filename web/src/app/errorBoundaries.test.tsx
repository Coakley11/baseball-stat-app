import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement, ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import ErrorBoundary from "./error";
import GlobalError from "./global-error";

const leaky = Object.assign(new Error("connect ECONNREFUSED http://10.1.2.3:8601 token=abc123"), { digest: "d1g3st" });

describe("error boundaries", () => {
  it("page boundary shows a generic message and a reference, never the error's text", async () => {
    const retry = vi.fn();
    render(<ErrorBoundary error={leaky} retry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
    expect(document.body.textContent).not.toMatch(/ECONNREFUSED|10\.1\.2\.3|abc123/);
    expect(screen.getByText(/Reference: d1g3st/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("page boundary copes with a thrown value that is not an Error", () => {
    render(<ErrorBoundary error={"just a string"} retry={() => undefined} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/Reference:/)).toBeNull();
  });

  it("global boundary is a full document with fixed text and a retry button", () => {
    // It replaces <html>, so it cannot be mounted inside the test container: check the markup it
    // produces, then call the retry button's handler from the element tree.
    const retry = vi.fn();
    const tree = GlobalError({ error: leaky, retry }) as ReactElement<{ children: ReactElement<{ children: ReactNode[] }> }>;
    const html = renderToStaticMarkup(tree);
    expect(html.startsWith("<html")).toBe(true);
    expect(html).toContain("Baseball Explorer is having trouble");
    expect(html).not.toMatch(/ECONNREFUSED|10\.1\.2\.3|abc123/);
    const button = (tree.props.children.props.children as ReactElement<{ onClick: () => void }>[]).find((c) => c.type === "button")!;
    button.props.onClick();
    expect(retry).toHaveBeenCalledOnce();
  });
});
