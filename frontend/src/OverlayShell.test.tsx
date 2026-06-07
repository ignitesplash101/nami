import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { OverlayShell } from "./OverlayShell";

function OverlayHarness({ onClose = () => {} }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <>
      <button onClick={() => setOpen(true)}>Open overlay</button>
      <OverlayShell
        isOpen={open}
        onClose={() => {
          onClose();
          setOpen(false);
        }}
        className="test-overlay"
        ariaLabel="Test overlay"
        title="Test"
        initialFocusRef={inputRef}
      >
        <input ref={inputRef} aria-label="First field" />
        <button>Last action</button>
      </OverlayShell>
    </>
  );
}

function pressTab(shiftKey = false) {
  document.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Tab", shiftKey, bubbles: true, cancelable: true })
  );
}

describe("OverlayShell", () => {
  it("focuses the initial element and restores focus to the opener", async () => {
    render(<OverlayHarness />);
    const opener = screen.getByText("Open overlay");
    opener.focus();

    fireEvent.click(opener);
    await waitFor(() => expect(screen.getByLabelText("First field")).toHaveFocus());

    fireEvent.click(screen.getByLabelText("Close"));
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it("closes from backdrop click", async () => {
    const onClose = vi.fn();
    const { container } = render(<OverlayHarness onClose={onClose} />);

    fireEvent.click(screen.getByText("Open overlay"));
    await waitFor(() => expect(screen.getByRole("dialog", { name: "Test overlay" })).toBeInTheDocument());

    const backdrop = container.querySelector(".drawer-backdrop");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop as Element);

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog", { name: "Test overlay" })).not.toBeInTheDocument();
  });

  it("keeps Tab focus inside the overlay", async () => {
    render(<OverlayHarness />);

    fireEvent.click(screen.getByText("Open overlay"));
    const first = await screen.findByLabelText("First field");
    await waitFor(() => expect(first).toHaveFocus());

    screen.getByText("Last action").focus();
    pressTab();
    expect(screen.getByLabelText("Close")).toHaveFocus();
  });
});
