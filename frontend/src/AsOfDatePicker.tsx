import { Clock } from "lucide-react";

interface AsOfDatePickerProps {
  value: string;            // YYYY-MM-DD; "" or latestClose means live
  latestClose: string;      // YYYY-MM-DD; latest NYSE regular close (the live anchor)
  onChange: (v: string) => void;
  disabled?: boolean;
}

export function AsOfDatePicker({ value, latestClose, onChange, disabled }: AsOfDatePickerProps) {
  const isBackdated = Boolean(value) && Boolean(latestClose) && value < latestClose;

  return (
    <div className="asof-picker">
      <label htmlFor="asof-input">
        <Clock size={13} /> As-of date
        <input
          id="asof-input"
          type="date"
          max={latestClose || undefined}
          value={value || latestClose}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
        />
      </label>
      {isBackdated ? (
        <button
          type="button"
          className="ghost-button asof-reset"
          onClick={() => onChange(latestClose)}
          disabled={disabled}
        >
          Reset to latest close
        </button>
      ) : null}
    </div>
  );
}

export function BackdatedModeBanner({
  effectiveDate,
  requestedDate
}: {
  effectiveDate: string;
  requestedDate: string;
}) {
  const resolved = effectiveDate !== requestedDate;
  return (
    <div className="backdated-banner">
      <strong style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <Clock size={14} /> Backdated mode
      </strong>
      <p>
        Data, factor history, and analog registry are filtered to{" "}
        <code>{effectiveDate}</code>
        {resolved ? (
          <>
            {" "}
            (resolved from your requested <code>{requestedDate}</code> — the prior NYSE
            trading day).
          </>
        ) : (
          <>.</>
        )}{" "}
        Narrative is grounded in the selected analog events only (no Google
        Search). <em>The LLM's parametric knowledge is not vintage-controlled</em>{" "}
        and may reference concepts learned from post-as-of training data — treat the
        analog envelope and shock magnitudes as the canonical record; the narrative
        is illustrative.
      </p>
    </div>
  );
}
