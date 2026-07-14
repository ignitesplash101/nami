import { render, screen } from "@testing-library/react";
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
});
