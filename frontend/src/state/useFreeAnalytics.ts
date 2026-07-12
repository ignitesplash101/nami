import { useEffect, useState } from "react";
import { profileBook, replayEvents } from "../api";
import { holdingsFromRows } from "../holdings";
import type { HoldingRow, HoldingUnits, PortfolioMode } from "../holdings";
import type { BookProfile, EventsReplay } from "../types";

/** Free pre-scenario surfaces (zero LLM). Cleared whenever the book selection
 * or custom holdings change so stale analytics can't describe another book. */
export function useFreeAnalytics(opts: {
  portfolioKey: string;
  portfolioMode: PortfolioMode;
  customRows: HoldingRow[];
  customUnits: HoldingUnits;
  customName: string;
  onError: (exc: unknown, action: "profile" | "replay") => void;
  clearError: () => void;
}) {
  const { portfolioKey, portfolioMode, customRows, customUnits, customName } = opts;
  const [bookProfile, setBookProfile] = useState<BookProfile | null>(null);
  const [profileBusy, setProfileBusy] = useState(false);
  const [eventsReplay, setEventsReplay] = useState<EventsReplay | null>(null);
  const [replayBusy, setReplayBusy] = useState(false);

  useEffect(() => {
    setBookProfile(null);
    setEventsReplay(null);
  }, [portfolioKey, portfolioMode, customRows, customUnits]);

  function freeEnginePayload() {
    return portfolioMode === "sample"
      ? { portfolio_key: portfolioKey }
      : {
          portfolio_holdings: holdingsFromRows(customRows),
          portfolio_name: customName || undefined
        };
  }

  async function handleProfileBook() {
    setProfileBusy(true);
    opts.clearError();
    try {
      setBookProfile(await profileBook(freeEnginePayload()));
    } catch (exc) {
      opts.onError(exc, "profile");
    } finally {
      setProfileBusy(false);
    }
  }

  async function handleEventsReplay() {
    setReplayBusy(true);
    opts.clearError();
    try {
      setEventsReplay(await replayEvents(freeEnginePayload()));
    } catch (exc) {
      opts.onError(exc, "replay");
    } finally {
      setReplayBusy(false);
    }
  }

  return { bookProfile, profileBusy, eventsReplay, replayBusy, handleProfileBook, handleEventsReplay };
}
