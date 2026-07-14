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
    expect(screen.getByText("Free, no LLM")).toBeInTheDocument();
    expect(screen.queryByText(/instant, free/i)).toBeNull();
  });

  it("shows honest cold-load copy while event replay is computing", () => {
    render(
      <KnowYourBook
        profile={null}
        replay={null}
        profileBusy={false}
        replayBusy
        onProfile={() => {}}
        onReplay={() => {}}
        unavailableReason={null}
        factorMeta={{}}
      />
    );
    fireEvent.click(screen.getByRole("radio", { name: "Event replay" }));

    expect(screen.getByRole("button", { name: "Loading historical events…" })).toBeDisabled();
    expect(screen.getByText(/first load can take a couple of minutes/i)).toBeInTheDocument();
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

  it("separates the profile summary from its horizontally safe diagnostics table", () => {
    render(
      <KnowYourBook
        bookName="Global quality"
        bookDescription="A diversified quality portfolio."
        benchmark="SPY"
        profile={{
          portfolio_name: "Global quality",
          as_of: "2026-07-10",
          factor_exposures: { market: 1.1 },
          per_name: [
            {
              ticker: "AAPL",
              weight: 1,
              r2: 0.8,
              r2_adj: 0.79,
              n_obs: 104,
              idio_vol_weekly: 0.03
            }
          ],
          idio_band_weekly: 0.02,
          n_factors: 1
        }}
        replay={null}
        profileBusy={false}
        replayBusy={false}
        onProfile={() => {}}
        onReplay={() => {}}
        unavailableReason={null}
        factorMeta={{}}
      />
    );

    expect(document.querySelector(".book-profile-summary")).not.toBeNull();
    const diagnostics = document.querySelector(".book-profile-diagnostics");
    expect(diagnostics).not.toBeNull();
    expect(diagnostics?.querySelector(".table-scroll")).not.toBeNull();
  });
});
