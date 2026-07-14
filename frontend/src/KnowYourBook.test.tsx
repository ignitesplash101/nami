import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KnowYourBook } from "./KnowYourBook";

describe("KnowYourBook", () => {
  it("carries the fullscreen affordance beside the segmented control", () => {
    render(
      <KnowYourBook
        profile={null}
        replay={null}
        profileBusy={false}
        replayBusy={false}
        onProfile={() => {}}
        onReplay={() => {}}
        unavailableReason={null}
        factorMeta={{}}
      />
    );
    expect(screen.getByRole("button", { name: "Expand book analytics" })).toBeInTheDocument();
  });

  it("uses the shared automatic-activation keyboard behavior", () => {
    render(
      <KnowYourBook
        profile={null}
        replay={null}
        profileBusy={false}
        replayBusy={false}
        onProfile={() => {}}
        onReplay={() => {}}
        unavailableReason={null}
        factorMeta={{}}
      />
    );
    const profile = screen.getByRole("radio", { name: "Book profile" });
    const events = screen.getByRole("radio", { name: "Event replay" });
    profile.focus();

    fireEvent.keyDown(profile, { key: "ArrowRight" });
    expect(events).toHaveAttribute("aria-checked", "true");
    expect(events).toHaveFocus();
    expect(screen.getByRole("button", { name: "Replay every historical event" })).toBeInTheDocument();
  });
});
