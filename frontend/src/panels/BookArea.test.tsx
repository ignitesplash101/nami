import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BookArea } from "./BookArea";

describe("BookArea", () => {
  it("folds portfolio identity into the single book-analytics card", () => {
    render(
      <BookArea
        selectedPortfolio={{
          key: "sample",
          name: "Global quality",
          description: "A diversified quality portfolio.",
          holdings: { AAPL: 0.6, MSFT: 0.4 },
          benchmark: "SPY"
        }}
        isCustomBook={false}
        customName=""
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

    expect(screen.getByRole("heading", { level: 2, name: "Your book" })).toBeInTheDocument();
    const analytics = screen.getByLabelText("Understand this book");
    expect(analytics).toHaveTextContent("Global quality");
    expect(analytics).toHaveTextContent("A diversified quality portfolio.");
    expect(analytics).toHaveTextContent("Benchmark: SPY");
    expect(document.querySelector(".book-header")).toBeNull();
  });
});
