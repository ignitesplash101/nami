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

  it("renders an action button that fires onAction then dismisses the toast", () => {
    const onAction = vi.fn();
    render(
      <ToastProvider>
        <PushButton message="Complete." actionLabel="View" onAction={onAction} />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText("push"));
    const action = screen.getByRole("button", { name: "View" });
    fireEvent.click(action);
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Complete.")).not.toBeInTheDocument();
  });

  it("pauses expiry while the toast holds keyboard focus and resumes on blur", () => {
    render(
      <ToastProvider>
        <PushButton message="Stay." durationMs={2000} actionLabel="View" onAction={() => {}} />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText("push"));
    const action = screen.getByRole("button", { name: "View" });

    act(() => action.focus());
    // Well past the deadline while focused — the View button must not vanish
    // under a keyboard user mid-read.
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(screen.getByText("Stay.")).toBeInTheDocument();

    act(() => action.blur());
    act(() => {
      vi.advanceTimersByTime(2100);
    });
    expect(screen.queryByText("Stay.")).not.toBeInTheDocument();
  });

  it("keeps focus and hover pauses independent (paused while either holds)", () => {
    render(
      <ToastProvider>
        <PushButton message="Both." durationMs={2000} actionLabel="View" onAction={() => {}} />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText("push"));
    const toast = screen.getByText("Both.").closest(".toast")!;
    const action = screen.getByRole("button", { name: "View" });

    // Hover AND focus, then release hover only — focus alone keeps it paused.
    fireEvent.mouseEnter(toast);
    act(() => action.focus());
    fireEvent.mouseLeave(toast);
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(screen.getByText("Both.")).toBeInTheDocument();

    // Release focus too — now both are clear, so it resumes and expires.
    act(() => action.blur());
    act(() => {
      vi.advanceTimersByTime(2100);
    });
    expect(screen.queryByText("Both.")).not.toBeInTheDocument();
  });

  it("renders a silent toast OUTSIDE the announced live region, action still focusable", () => {
    render(
      <ToastProvider>
        <PushButton
          message="Scenario complete — -1.00%"
          variant="success"
          silent
          actionLabel="View"
          onAction={() => {}}
        />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText("push"));

    const region = screen.getByRole("status");
    const toast = screen.getByText("Scenario complete — -1.00%").closest<HTMLElement>(".toast")!;
    // Single-announcer rule: the completion toast must not be spoken by the
    // toast stack's live region (App's region already announces run lifecycle).
    expect(region).not.toContainElement(toast);

    // ...but the action must remain keyboard-reachable (never inside an
    // aria-hidden subtree).
    const action = screen.getByRole("button", { name: "View" });
    expect(action.closest("[aria-hidden='true']")).toBeNull();
    act(() => action.focus());
    expect(action).toHaveFocus();
  });
});
