import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import { formatPercent, formatSignedCurrency } from "../charts";
import { GLOSSARY } from "../copy/glossary";
import { InfoTip } from "../copy/InfoTip";
import type { TransmissionModel, TransmissionRow } from "../impact";

function signedPercent(value: number, digits = 2): string {
  return `${value > 0 ? "+" : ""}${formatPercent(value, digits)}`;
}

const SEVERITY_COPY: Record<TransmissionRow["severity"], string | null> = {
  beyond: "Beyond every matched event",
  within: null,
  none: null
};

/** Scenario → P&L transmission: for every driver, the move the scenario applies
 * (against that driver's realized moves in each matched historical event) and
 * what the move does to this portfolio. Plain token CSS on percent positions —
 * no chart runtime — so it renders on the first results paint. The strip column
 * is scaled per row (each driver against its own history); the effect column
 * shares ONE scale so bar lengths compare directly. */
export function TransmissionChart({
  model,
  showDollars,
  nav,
  currency,
  degraded,
  initialRows
}: {
  model: TransmissionModel;
  showDollars: boolean;
  nav: number | null;
  currency: string;
  /** True when the result carries no conditional attribution (naive fallback). */
  degraded: boolean;
  initialRows: number;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const idBase = useId();
  const dollars = showDollars && nav != null;
  const fmtEffect = (value: number) =>
    dollars ? formatSignedCurrency(value * (nav ?? 0), currency) : signedPercent(value);
  const visibleRows = showAll ? model.rows : model.rows.slice(0, initialRows);
  const hiddenCount = model.rows.length - visibleRows.length;

  if (!model.rows.length) {
    return (
      <p className="muted tx-empty">
        No driver moved this portfolio — the scenario applied no material shocks.
      </p>
    );
  }

  return (
    <div className="tx-chart" role="group" aria-label="How the scenario reaches this portfolio">
      <div className="tx-head" aria-hidden="true">
        <span className="tx-head-name">Driver</span>
        <span className="tx-head-shock">Scenario move</span>
        <span className="tx-head-impact">Effect on your P&amp;L</span>
      </div>
      <ol className="tx-rows">
        {visibleRows.map((row) => {
          const open = expanded === row.id;
          const detailId = `${idBase}-${row.id}`;
          const stemLeft = Math.min(row.strip.zeroPct, row.strip.shockPct);
          const stemWidth = Math.abs(row.strip.shockPct - row.strip.zeroPct);
          const analogSpan = row.analogs.length
            ? `; in ${row.analogs.length} matched events it moved ${row.analogs
                .map((analog) => signedPercent(analog.value, 1))
                .join(", ")}`
            : "";
          const severity = SEVERITY_COPY[row.severity];
          return (
            <li key={row.id} className={`tx-row ${row.kind}${open ? " is-open" : ""}`}>
              <button
                type="button"
                className="tx-row-button"
                aria-expanded={open}
                aria-controls={detailId}
                aria-label={`${row.label}: scenario move ${signedPercent(row.shock, 1)}${analogSpan}; effect on P&L ${fmtEffect(row.contribution)}. ${open ? "Hide" : "Show"} reasoning.`}
                onClick={() => setExpanded(open ? null : row.id)}
              >
                <span className="tx-name">
                  <span className="tx-label">{row.label}</span>
                  <span className="tx-group">
                    {row.groupLabel}
                    {severity ? <span className="tx-severity">{severity}</span> : null}
                  </span>
                </span>
                <span className="tx-shock">
                  <span className="tx-strip">
                    <span className="tx-strip-axis" />
                    {row.range ? (
                      <span
                        className="tx-strip-range"
                        style={{
                          left: `${row.range.lowPct}%`,
                          width: `${Math.max(row.range.highPct - row.range.lowPct, 0.5)}%`
                        }}
                      />
                    ) : null}
                    <span className="tx-strip-zero" style={{ left: `${row.strip.zeroPct}%` }} />
                    <span
                      className="tx-strip-stem"
                      style={{ left: `${stemLeft}%`, width: `${stemWidth}%` }}
                    />
                    {row.analogs.map((analog) => (
                      <span
                        key={analog.eventId}
                        className="tx-strip-analog"
                        style={{ left: `${analog.pct}%` }}
                        title={`${analog.name}: ${signedPercent(analog.value, 1)}`}
                      />
                    ))}
                    <span className="tx-strip-shock" style={{ left: `${row.strip.shockPct}%` }} />
                  </span>
                  <span className="tx-value tx-shock-value">{signedPercent(row.shock, 1)}</span>
                </span>
                <span className="tx-impact">
                  <span className="tx-bar-track">
                    <span className="tx-bar-zero" style={{ left: `${model.impactZeroPct}%` }} />
                    <span
                      className={`tx-bar ${row.contribution < 0 ? "down" : "up"}`}
                      style={{
                        left: `${row.impact.leftPct}%`,
                        width: `${Math.max(row.impact.widthPct, 0.4)}%`
                      }}
                    />
                  </span>
                  <span className="tx-value tx-impact-value">{fmtEffect(row.contribution)}</span>
                </span>
                <ChevronDown className="tx-chevron" size={16} aria-hidden="true" />
              </button>
              <div id={detailId} className="tx-detail" hidden={!open}>
                {row.reasoning ? <p>{row.reasoning}</p> : null}
                {row.analogs.length ? (
                  <ul className="tx-analog-list" aria-label={`${row.label} in matched events`}>
                    {row.analogs.map((analog) => (
                      <li key={analog.eventId}>
                        <span>{analog.name}</span>
                        <strong>{signedPercent(analog.value, 1)}</strong>
                      </li>
                    ))}
                  </ul>
                ) : row.kind === "single-name" ? (
                  <p className="muted">
                    A company-specific move on top of the market drivers; no historical event
                    measures it.
                  </p>
                ) : (
                  <p className="muted">No matched event covers this driver.</p>
                )}
                {row.range ? (
                  <p className="muted">
                    Typical matched-event range (p10–p90): {signedPercent(row.range.low, 1)} to{" "}
                    {signedPercent(row.range.high, 1)}.
                  </p>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
      {hiddenCount > 0 || showAll ? (
        <button
          type="button"
          className="ghost-button tx-more"
          aria-expanded={showAll}
          onClick={() => setShowAll((value) => !value)}
        >
          {showAll ? "Show the largest drivers only" : `Show all ${model.rows.length} drivers`}
        </button>
      ) : null}
      <dl className="tx-totals">
        <div>
          <dt>Market drivers</dt>
          <dd>{fmtEffect(model.factorTotal)}</dd>
        </div>
        <div>
          <dt>Company-specific</dt>
          <dd>{fmtEffect(model.singleNameTotal)}</dd>
        </div>
        {model.residual !== 0 ? (
          <div>
            <dt>Unreconciled</dt>
            <dd>{fmtEffect(model.residual)}</dd>
          </div>
        ) : null}
        <div className="tx-total">
          <dt>Modeled total</dt>
          <dd>{fmtEffect(model.total)}</dd>
        </div>
      </dl>
      <div className="tx-legend">
        <span className="tx-key">
          <span className="tx-key-shock" aria-hidden="true" /> Scenario move
        </span>
        {model.analogCount ? (
          <span className="tx-key">
            <span className="tx-key-analog" aria-hidden="true" /> One matched historical event
          </span>
        ) : null}
        <span className="tx-key">
          <span className="tx-key-range" aria-hidden="true" /> Typical range (p10–p90)
        </span>
        <span className="tx-key-note">
          Each move is scaled to its own history; effects share one scale.
          <InfoTip label="About the scenario move">
            {GLOSSARY.scenarioMove.plain} {GLOSSARY.scenarioMove.detail}
          </InfoTip>
          <InfoTip label="About the effect on your P&L">
            {GLOSSARY.pnlEffect.plain}{" "}
            {degraded ? GLOSSARY.pnlEffect.naiveDetail : GLOSSARY.pnlEffect.detail}
          </InfoTip>
        </span>
      </div>
    </div>
  );
}
