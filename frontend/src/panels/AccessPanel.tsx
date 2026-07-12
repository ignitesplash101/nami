import { useState } from "react";
import type { RefObject } from "react";
import { Lock, LogOut, Shield, Unlock } from "lucide-react";
import { ApiError, lock, toApiError, unlock } from "../api";
import { ErrorNotice } from "../ErrorNotice";
import type { AccessResponse } from "../types";

export function AccessPanel({
  access,
  onAccessChange,
  passcodeInputRef
}: {
  access: AccessResponse | null;
  onAccessChange: (access: AccessResponse, opts?: { intentional?: boolean }) => void;
  passcodeInputRef?: RefObject<HTMLInputElement>;
}) {
  const [passcode, setPasscode] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<ApiError | string | null>(null);
  const isAdmin = access?.access_mode === "admin";

  async function handleUnlock() {
    setBusy(true);
    setMessage(null);
    try {
      const response = await unlock(passcode);
      onAccessChange(response, { intentional: true });
      setPasscode("");
    } catch (exc) {
      setMessage(toApiError(exc));
    } finally {
      setBusy(false);
    }
  }

  async function handleLock() {
    setBusy(true);
    try {
      const response = await lock();
      // A deliberate lock must not raise the session-expired banner.
      onAccessChange(response, { intentional: true });
    } catch (exc) {
      setMessage(toApiError(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel access-panel">
      <div className="panel-title">
        {isAdmin ? <Unlock size={16} /> : <Lock size={16} />}
        <span>{isAdmin ? "Admin mode" : "Visitor mode"}</span>
      </div>
      <p className="muted">
        {isAdmin
          ? "Unrestricted controls are enabled for this browser session."
          : "Visitors can run sample scenarios on sample portfolios only."}
      </p>
      {isAdmin ? (
        <button className="ghost-button" onClick={handleLock} disabled={busy}>
          <LogOut size={15} /> Return to visitor mode
        </button>
      ) : (
        <form
          className="unlock-row"
          onSubmit={(event) => {
            event.preventDefault();
            if (passcode && !busy && access?.admin_available) void handleUnlock();
          }}
        >
          <input
            ref={passcodeInputRef}
            value={passcode}
            onChange={(event) => setPasscode(event.target.value)}
            type="password"
            autoComplete="current-password"
            placeholder="Admin passcode"
            aria-label="Admin passcode"
            aria-invalid={Boolean(message)}
            aria-describedby={message ? "unlock-message" : undefined}
            disabled={!access?.admin_available || busy}
          />
          <button type="submit" disabled={!passcode || busy || !access?.admin_available}>
            <Shield size={15} /> Unlock
          </button>
        </form>
      )}
      {message ? <ErrorNotice variant="inline" error={message} id="unlock-message" /> : null}
    </section>
  );
}
