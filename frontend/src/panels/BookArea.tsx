import { KnowYourBook } from "../KnowYourBook";
import type { BookProfile, EventsReplay, FactorMetadataMap, SamplePortfolio } from "../types";

/** The "Your book" area: one analytics card with responsive portfolio context.
 * Data state lives in App (useFreeAnalytics) so it survives area switches and
 * clears on book changes. */
export function BookArea({
  selectedPortfolio,
  isCustomBook,
  customName,
  profile,
  replay,
  profileBusy,
  replayBusy,
  onProfile,
  onReplay,
  unavailableReason,
  factorMeta
}: {
  selectedPortfolio?: SamplePortfolio;
  isCustomBook: boolean;
  customName: string;
  profile: BookProfile | null;
  replay: EventsReplay | null;
  profileBusy: boolean;
  replayBusy: boolean;
  onProfile: () => void;
  onReplay: () => void;
  unavailableReason: string | null;
  factorMeta: FactorMetadataMap;
}) {
  const name = isCustomBook ? customName || "Custom book" : selectedPortfolio?.name ?? "—";
  const description = isCustomBook
    ? "Your custom holdings — edit them in the portfolio setup."
    : selectedPortfolio?.description ?? "";
  return (
    <section className="book-area" aria-label="Your book">
      <h2 className="area-heading">Your book</h2>
      <KnowYourBook
        bookName={name}
        bookDescription={description}
        benchmark={!isCustomBook ? selectedPortfolio?.benchmark ?? null : null}
        profile={profile}
        replay={replay}
        profileBusy={profileBusy}
        replayBusy={replayBusy}
        onProfile={onProfile}
        onReplay={onReplay}
        unavailableReason={unavailableReason}
        factorMeta={factorMeta}
      />
    </section>
  );
}
