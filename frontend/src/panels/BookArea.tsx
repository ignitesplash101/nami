import { KnowYourBook } from "../KnowYourBook";
import type { BookProfile, EventsReplay, FactorMetadataMap, SamplePortfolio } from "../types";

/** The "Your book" area: identity header + the free, zero-LLM analytics
 * (book profile / event replay) promoted from the results empty state to a
 * first-class destination. Data state lives in App (useFreeAnalytics) so it
 * survives area switches and clears on book changes. */
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
      <div className="result-card book-header">
        <p className="eyebrow">Your book</p>
        <h2>{name}</h2>
        {description ? <p className="muted">{description}</p> : null}
        {!isCustomBook && selectedPortfolio?.benchmark ? (
          <p className="muted">
            Benchmark: <code>{selectedPortfolio.benchmark}</code>
          </p>
        ) : null}
      </div>
      <KnowYourBook
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
