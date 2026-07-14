import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CommandPalette } from "./CommandPalette";

const actions = [
  { id: "run", label: "Run scenario", run: vi.fn() },
  { id: "book", label: "Open your book", run: vi.fn() },
  { id: "methodology", label: "Read methodology", run: vi.fn() }
];

describe("CommandPalette", () => {
  it("connects the combobox, listbox, and selected option with stable IDs", () => {
    const { rerender } = render(
      <CommandPalette isOpen onClose={() => {}} actions={actions} />
    );

    const input = screen.getByRole("combobox", { name: "Command search" });
    const listbox = screen.getByRole("listbox", { name: "Commands" });
    const first = screen.getByRole("option", { name: "Run scenario" });
    expect(input).toHaveAttribute("aria-controls", listbox.id);
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute("aria-autocomplete", "list");
    expect(input).toHaveAttribute("aria-activedescendant", first.id);
    expect(first).toHaveAttribute("aria-selected", "true");

    const listboxId = listbox.id;
    const optionId = first.id;
    rerender(<CommandPalette isOpen onClose={() => {}} actions={actions} />);
    expect(screen.getByRole("listbox", { name: "Commands" })).toHaveAttribute("id", listboxId);
    expect(screen.getByRole("option", { name: "Run scenario" })).toHaveAttribute("id", optionId);
  });

  it("navigates with arrows, Home, and End while focus stays in the combobox", () => {
    render(<CommandPalette isOpen onClose={() => {}} actions={actions} />);
    const input = screen.getByRole("combobox", { name: "Command search" });
    input.focus();

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getByRole("option", { name: "Open your book" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(input).toHaveFocus();

    fireEvent.keyDown(input, { key: "End" });
    expect(screen.getByRole("option", { name: "Read methodology" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    fireEvent.keyDown(input, { key: "Home" });
    expect(screen.getByRole("option", { name: "Run scenario" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });

  it("runs the active command with Enter", () => {
    const onClose = vi.fn();
    const run = vi.fn();
    render(
      <CommandPalette
        isOpen
        onClose={onClose}
        actions={[{ id: "run", label: "Run scenario", run }]}
      />
    );

    fireEvent.keyDown(screen.getByRole("combobox", { name: "Command search" }), {
      key: "Enter"
    });
    expect(onClose).toHaveBeenCalledOnce();
    expect(run).toHaveBeenCalledOnce();
  });

  it("clears active-descendant and ignores navigation safely when no results match", () => {
    render(<CommandPalette isOpen onClose={() => {}} actions={actions} />);
    const input = screen.getByRole("combobox", { name: "Command search" });
    fireEvent.change(input, { target: { value: "no such command" } });

    expect(screen.getByText("No matching commands")).toBeInTheDocument();
    expect(input).not.toHaveAttribute("aria-activedescendant");
    expect(() => {
      fireEvent.keyDown(input, { key: "ArrowDown" });
      fireEvent.keyDown(input, { key: "Home" });
      fireEvent.keyDown(input, { key: "End" });
      fireEvent.keyDown(input, { key: "Enter" });
    }).not.toThrow();
  });
});
