import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

function Boom(): never {
  throw new Error("boom");
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // React logs the caught error; keep test output clean.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders children when nothing throws", () => {
    render(
      <ErrorBoundary>
        <p>healthy</p>
      </ErrorBoundary>
    );
    expect(screen.getByText("healthy")).toBeInTheDocument();
  });

  it("renders the fallback when a child throws and reloads on demand", () => {
    const reload = vi.fn();
    render(
      <ErrorBoundary reload={reload}>
        <Boom />
      </ErrorBoundary>
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
    fireEvent.click(screen.getByText("Reload workbench"));
    expect(reload).toHaveBeenCalledOnce();
  });
});
