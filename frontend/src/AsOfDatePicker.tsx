import { Clock } from "lucide-react";

interface AsOfDatePickerProps {
  value: string;            // YYYY-MM-DD; "" or today means live
  onChange: (v: string) => void;
  disabled?: boolean;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function AsOfDatePicker({ value, onChange, disabled }: AsOfDatePickerProps) {
  const today = todayIso();
  const isBackdated = Boolean(value) && value < today;

  return (
    <div className="asof-picker">
      <label htmlFor="asof-input">
        <Clock size={13} /> As-of date
        <input
          id="asof-input"
          type="date"
          max={today}
          value={value || today}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
        />
      </label>
      {isBackdated ? (
        <button
          type="button"
          className="ghost-button asof-reset"
          onClick={() => onChange(today)}
          disabled={disabled}
        >
          Reset to today
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
      <strong>🕰 Backdated mode</strong>
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
