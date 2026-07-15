import { useCallback, useEffect, useState } from "react";
import { Copy, Download, RefreshCw } from "lucide-react";
import { downloadExport, getAuditLog, getStatus, getUsage, toApiError } from "./api";
import type { ApiError } from "./api";
import { ErrorNotice } from "./ErrorNotice";
import { formatCurrency } from "./charts";
import { relativeTime } from "./format";
import { OverlayShell } from "./OverlayShell";
import { TableScroll } from "./TableScroll";
import { useToasts } from "./toast";
import type { AuditEntry, StatusResponse, UsageSummary } from "./types";

interface OpsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  // Opens the type-to-confirm purge dialog AFTER this drawer closes — two
  // useOverlay overlays must never be open at once (both Esc-listen on window).
  onRequestPurge: () => void;
  onForbidden?: () => void;
}

function meterClass(used: number, cap: number): string {
  if (cap <= 0) return "ops-meter-fill";
  const ratio = used / cap;
  if (ratio >= 1) return "ops-meter-fill over";
  if (ratio >= 0.8) return "ops-meter-fill warn";
  return "ops-meter-fill";
}

function meterWidth(used: number, cap: number): string {
  if (cap <= 0) return "0%";
  return `${Math.min(100, (used / cap) * 100).toFixed(1)}%`;
}

export function OpsDrawer({ isOpen, onClose, onRequestPurge, onForbidden }: OpsDrawerProps) {
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | string | null>(null);
  const [exporting, setExporting] = useState(false);
  const { push } = useToasts();

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([getUsage(), getStatus(), getAuditLog(100)])
      .then(([usageResponse, statusResponse, auditResponse]) => {
        setUsage(usageResponse);
        setStatus(statusResponse);
        setAudit(auditResponse);
      })
      .catch((exc) => {
        const err = toApiError(exc);
        if (err.kind === "forbidden") onForbidden?.();
        setError(err);
      })
      .finally(() => setLoading(false));
    // onForbidden is a stable App-level callback.
  }, []);

  // Fetch only while open — visitors never mount this and a closed drawer
  // costs nothing.
  useEffect(() => {
    if (isOpen) load();
  }, [isOpen, load]);

  async function handleExport() {
    setExporting(true);
    setError(null);
    try {
      const blob = await downloadExport();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `nami-export-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      push({ variant: "success", message: "Export downloaded." });
    } catch (exc) {
      const err = toApiError(exc);
      if (err.kind === "forbidden") onForbidden?.();
      setError(err);
    } finally {
      setExporting(false);
    }
  }

  async function copyRequestId(requestId: string) {
    try {
      await navigator.clipboard.writeText(requestId);
      push({ message: "Request id copied.", variant: "info" });
    } catch {
      // Clipboard unavailable (insecure origin) — no-op.
    }
  }

  return (
    <OverlayShell
      isOpen={isOpen}
      onClose={onClose}
      className="drawer-panel ops-drawer"
      ariaLabel="Operations console"
      title="Operations console"
    >
      <div className="drawer-body">
        {error ? <ErrorNotice variant="inline" error={error} onRetry={load} /> : null}
        {loading && !usage ? <p className="muted">Loading…</p> : null}

        {usage ? (
          <section className="ops-section" aria-label="Usage today">
            <p className="eyebrow">Usage today ({usage.day})</p>
            <div className="ops-metric">
              <span>Runs</span>
              <span>
                {usage.runs} / {usage.run_cap}
              </span>
            </div>
            <div className="ops-meter" aria-hidden="true">
              <div
                className={meterClass(usage.runs, usage.run_cap)}
                style={{ width: meterWidth(usage.runs, usage.run_cap) }}
              />
            </div>
            <div className="ops-metric">
              <span>Est. cost</span>
              <span>
                {formatCurrency(usage.spent_usd, "USD", 2)} /{" "}
                {formatCurrency(usage.cost_cap_usd, "USD", 2)}
                {usage.reserved_usd > 0 ? (
                  <span className="muted"> (+{formatCurrency(usage.reserved_usd, "USD", 2)} reserved)</span>
                ) : null}
              </span>
            </div>
            <div className="ops-meter" aria-hidden="true">
              <div
                className={meterClass(usage.spent_usd + usage.reserved_usd, usage.cost_cap_usd)}
                style={{ width: meterWidth(usage.spent_usd + usage.reserved_usd, usage.cost_cap_usd) }}
              />
            </div>
            <div className="ops-metric">
              <span>Tokens in / out</span>
              <span>
                {usage.tokens_in.toLocaleString("en-US")} / {usage.tokens_out.toLocaleString("en-US")}
              </span>
            </div>
            <div className="ops-metric">
              <span>Gemini calls</span>
              <span>{usage.calls}</span>
            </div>
            {status ? (
              <p className="muted ops-status-line">
                {status.environment} · {status.engine_mode} · {status.model_id} · prompt{" "}
                {status.prompt_version} · {status.ready ? "ready" : "degraded"}
              </p>
            ) : null}
          </section>
        ) : null}

        <section className="ops-section ops-audit" aria-label="Audit log">
          <div className="card-heading">
            <p className="eyebrow">Audit log</p>
            <button
              type="button"
              className="ghost-button table-export-btn"
              onClick={load}
              disabled={loading}
              aria-label="Refresh operations data"
            >
              <RefreshCw size={13} /> Refresh
            </button>
          </div>
          {audit.length === 0 ? (
            <p className="muted">No audit entries yet.</p>
          ) : (
            <TableScroll>
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Action</th>
                    <th>Target</th>
                    <th>Request</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.map((entry, index) => (
                    <tr key={`${entry.at}-${index}`}>
                      <td title={entry.at}>{relativeTime(entry.at)}</td>
                      <td>{entry.action}</td>
                      <td>
                        {entry.target_type}
                        {entry.target_id ? ` · ${entry.target_id.slice(0, 8)}` : ""}
                      </td>
                      <td>
                        {entry.request_id ? (
                          <span className="error-ref">
                            <code>{entry.request_id.slice(0, 8)}</code>
                            <button
                              type="button"
                              aria-label={`Copy request id for ${entry.action}`}
                              onClick={() => void copyRequestId(entry.request_id ?? "")}
                            >
                              <Copy size={12} />
                            </button>
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          )}
        </section>

        <section className="ops-section" aria-label="Export">
          <p className="eyebrow">Export</p>
          <p className="muted">
            Full JSON export of saved scenarios, portfolios, and snapshots — suitable for backup
            or offline analysis.
          </p>
          <button type="button" className="ghost-button" onClick={handleExport} disabled={exporting}>
            <Download size={14} /> {exporting ? "Exporting…" : "Download export (JSON)"}
          </button>
        </section>

        <section className="ops-section ops-danger" aria-label="Danger zone">
          <p className="eyebrow">Danger zone</p>
          <p className="muted">
            Purge permanently deletes all saved scenarios, portfolios, and snapshots. The audit
            log is preserved.
          </p>
          <button type="button" className="ghost-button danger" onClick={onRequestPurge}>
            Purge all data…
          </button>
        </section>
      </div>
    </OverlayShell>
  );
}
