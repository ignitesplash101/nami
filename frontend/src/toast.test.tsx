import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider, useToasts } from "./toast";
import type { ToastInput } from "./toast";

function PushButton(props: ToastInput) {
  const { push } = useToasts();
  return (
    <button type="button" onClick={() => push(props)}>
      push
    </button>
  );
}

describe("ToastProvider", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("renders pushed toasts inside an aria-live status region", () => {
    render(
      <ToastProvider>
        <PushButton message="Scenario saved to library." variant="success" />
      </ToastProvider>
    );
    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("aria-live", "polite");

    fireEvent.click(screen.getByText("push"));
    expect(screen.getByText("Scenario saved to library.")).toBeInTheDocument();
    expect(screen.getByText("Scenario saved to library.").closest(".toast")).toHaveClass(
      "toast-success"
    );
  });

  it("auto-dismisses after the duration", () => {
    render(
      <ToastProvider>
        <PushButton message="Done." durationMs={2000} />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText("push"));
    expect(screen.getByText("Done.")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(2100);
    });
    expect(screen.queryByText("Done.")).not.toBeInTheDocument();
  });

  it("pauses the countdown on hover and resumes on leave", () => {
    render(
      <ToastProvider>
        <PushButton message="Hover me." durationMs={2000} />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText("push"));
    const toast = screen.getByText("Hover me.").closest(".toast")!;

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    fireEvent.mouseEnter(toast);
    // Way past the original deadline while hovered — must still be visible.
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(screen.getByText("Hover me.")).toBeInTheDocument();

    fireEvent.mouseLeave(toast);
    act(() => {
      vi.advanceTimersByTime(1100);
    });
    expect(screen.queryByText("Hover me.")).not.toBeInTheDocument();
  });

  it("dismisses on the close button", () => {
    render(
      <ToastProvider>
        <PushButton message="Close me." />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText("push"));
    fireEvent.click(screen.getByLabelText("Dismiss notification"));
    expect(screen.queryByText("Close me.")).not.toBeInTheDocument();
  });

  it("no-ops outside a provider instead of crashing isolated component tests", () => {
    render(<PushButton message="orphan" />);
    fireEvent.click(screen.getByText("push"));
    expect(screen.queryByText("orphan")).not.toBeInTheDocument();
  });
});
