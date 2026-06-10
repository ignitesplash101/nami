import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";

function renderDialog(props: Partial<Parameters<typeof ConfirmDialog>[0]> = {}) {
  const onClose = vi.fn();
  const onConfirm = vi.fn();
  render(
    <ConfirmDialog
      isOpen
      onClose={onClose}
      onConfirm={onConfirm}
      title="Delete saved scenario"
      body={<p>Delete this scenario? This cannot be undone.</p>}
      confirmLabel="Delete"
      danger
      {...props}
    />
  );
  return { onClose, onConfirm };
}

describe("ConfirmDialog", () => {
  it("renders an aria-modal dialog and confirms on click", () => {
    const { onConfirm } = renderDialog();
    const dialog = screen.getByRole("dialog", { name: "Delete saved scenario" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    fireEvent.click(screen.getByText("Delete"));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("cancel calls onClose without confirming", () => {
    const { onClose, onConfirm } = renderDialog();
    fireEvent.click(screen.getByText("Cancel"));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("gates the confirm button behind the type-to-confirm token", () => {
    const { onConfirm } = renderDialog({ typeToConfirm: "DELETE" });
    const confirm = screen.getByText("Delete").closest("button")!;
    expect(confirm).toBeDisabled();

    const input = screen.getByLabelText(/Confirmation/);
    fireEvent.change(input, { target: { value: "delete" } });
    expect(confirm).toBeDisabled(); // exact match required

    fireEvent.change(input, { target: { value: "DELETE" } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("disables both actions while busy", () => {
    renderDialog({ busy: true });
    expect(screen.getByText("Working…").closest("button")).toBeDisabled();
    expect(screen.getByText("Cancel").closest("button")).toBeDisabled();
  });

  it("renders nothing when closed", () => {
    render(
      <ConfirmDialog
        isOpen={false}
        onClose={() => {}}
        onConfirm={() => {}}
        title="Hidden"
        body="never shown"
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
