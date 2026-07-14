import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SavedScenariosPanel } from "./SavedScenariosPanel";
import { useOverlayManager } from "./state/useOverlayManager";

const listSavedScenarios = vi.fn();

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return {
    ...actual,
    listSavedScenarios: (...args: unknown[]) => listSavedScenarios(...args)
  };
});

function Harness() {
  const overlays = useOverlayManager();
  return (
    <>
      <SavedScenariosPanel
        reloadKey={0}
        onOpen={() => {}}
        isDeleteConfirmOpen={overlays.savedDeleteConfirm.isOpen}
        onOpenDeleteConfirm={overlays.openSavedDeleteConfirm}
        onCloseDeleteConfirm={overlays.savedDeleteConfirm.close}
      />
      <button type="button" onClick={overlays.openCommandPalette}>
        Open command palette
      </button>
      <button type="button" onClick={overlays.commandPalette.close}>
        Close command palette
      </button>
      <button type="button" onClick={overlays.openSavedDeleteConfirm}>
        Reopen delete registry
      </button>
    </>
  );
}

describe("SavedScenariosPanel", () => {
  beforeEach(() => {
    listSavedScenarios.mockResolvedValue([
      {
        id: "saved-1",
        name: "Quarterly stress",
        tags: [],
        created_at: "2026-07-14T00:00:00Z",
        owner_label: null,
        portfolio_name: "Global quality",
        portfolio_key: "sample",
        requested_as_of_date: "2026-07-14",
        effective_as_of_date: "2026-07-14",
        narrative_mode: "grounded_current",
        total_pnl: -0.12
      }
    ]);
  });

  it("clears the pending saved item whenever another registry overlay closes delete", async () => {
    render(<Harness />);
    const deleteButton = await screen.findByRole("button", { name: "Delete Quarterly stress" });

    deleteButton.focus();
    act(() => deleteButton.click());
    expect(screen.getByRole("dialog", { name: "Delete saved scenario" })).toHaveTextContent(
      "Quarterly stress"
    );
    expect(document.body.style.overflow).toBe("hidden");

    act(() => screen.getByRole("button", { name: "Open command palette" }).click());
    expect(screen.queryByRole("dialog", { name: "Delete saved scenario" })).toBeNull();
    expect(document.body.style.overflow).toBe("hidden");
    await waitFor(() => expect(deleteButton).toHaveFocus());

    act(() => screen.getByRole("button", { name: "Close command palette" }).click());
    expect(document.body.style.overflow).toBe("");
    act(() => screen.getByRole("button", { name: "Reopen delete registry" }).click());
    expect(screen.getByRole("dialog", { name: "Delete saved scenario" })).toHaveTextContent(
      "this scenario"
    );
    expect(screen.getByRole("dialog", { name: "Delete saved scenario" })).not.toHaveTextContent(
      "Quarterly stress"
    );
  });
});
