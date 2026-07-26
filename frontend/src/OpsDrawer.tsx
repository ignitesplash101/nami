import { useCallback, useEffect, useState } from "react";
import { Copy, Download, RefreshCw } from "lucide-react";
import { downloadExport, getAuditLog, getMetrics, getStatus, getUsage, toApiError } from "./api";
import type { ApiError } from "./api";
import { ErrorNotice } from "./ErrorNotice";
import { formatCurrency } from "./charts";
import { relativeTime } from "./format";
import { OverlayShell } from "./OverlayShell";
import { TableScroll } from "./TableScroll";
import { useToasts } from "./toast";
import type { AuditEntry, MetricsResponse, StatusResponse, UsageSummary } from "./types";

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
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  // The scheduled pre-warm makes ~16 machine runs every weekday; excluded by
  // default so it can't dominate the numbers, but the toggle keeps that visible.
  const [includeSynthetic, setIncludeSynthetic] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | string | null>(null);
  const [exporting, setExporting] = useState(false);
  const { push } = useToasts();

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      getUsage(),
      getStatus(),
      getAuditLog(100),
      // Its OWN catch: Promise.all is all-or-nothing, and a Logging API hiccup
      // must dim one panel rather than blank the whole console.
      getMetrics(7, includeSynthetic).catch(() => null)
    ])
      .then(([usageResponse, statusResponse, auditResponse, metricsResponse]) => {
        setUsage(usageResponse);
        setStatus(statusResponse);
        setAudit(auditResponse);
        setMetrics(metricsResponse);
      })
      .catch((exc) => {
        const err = toApiError(exc);
        if (err.kind === "forbidden") onForbidden?.();
        setError(err);
      })
      .finally(() => setLoading(false));
    // onForbidden is a stable App-level callback.
  }, [includeSynthetic]);

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

        {metrics ? (
          <section className="ops-section" aria-label="Usage metrics">
            <div className="card-heading">
              <p className="eyebrow">Last {metrics.days} days</p>
              <label className="ops-toggle">
                <input
                  type="checkbox"
                  checked={includeSynthetic}
                  onChange={(event) => setIncludeSynthetic(event.target.checked)}
                />
                Include pre-warm
              </label>
            </div>

            {!metrics.logs_available ? (
              <p className="muted">
                Traffic unavailable — the runtime service account needs{" "}
                <code>roles/logging.viewer</code>. Cost and quota below still apply.
              </p>
            ) : (
              <>
                <div className="ops-metric">
                  <span>Unique visitors</span>
                  <strong>{Number(metrics.totals.unique_visitors ?? 0).toLocaleString("en-US")}</strong>
                </div>
                <div className="ops-metric">
                  <span>Requests</span>
                  <strong>{Number(metrics.totals.requests ?? 0).toLocaleString("en-US")}</strong>
                </div>
                <div className="ops-metric">
                  <span>Scenario runs (visitor / admin)</span>
                  <strong>
                    {Number(metrics.totals.visitor_runs ?? 0)} / {Number(metrics.totals.admin_runs ?? 0)}
                  </strong>
                </div>
                {metrics.totals.cache_hit_rate != null ? (
                  <div className="ops-metric">
                    <span>Cache hit rate</span>
                    <strong>{(Number(metrics.totals.cache_hit_rate) * 100).toFixed(0)}%</strong>
                  </div>
                ) : null}
                <div className="ops-metric">
                  <span>Errors</span>
                  <strong>{Number(metrics.totals.errors ?? 0).toLocaleString("en-US")}</strong>
                </div>
                {metrics.totals.latency_p95_ms != null ? (
                  <div className="ops-metric">
                    <span>Latency p50 / p95</span>
                    <strong>
                      {Number(metrics.totals.latency_p50_ms)}ms / {Number(metrics.totals.latency_p95_ms)}ms
                    </strong>
                  </div>
                ) : null}

                {metrics.scenario_runs.length ? (
                  <>
                    <p className="eyebrow ops-subhead">Runs by scenario</p>
                    <div className="exposure-bars">
                      {metrics.scenario_runs.map((row) => (
                        <div className="exposure-bar-row" key={row.key}>
                          <span className="exposure-bar-label">{row.key}</span>
                          <span className="exposure-bar-track">
                            <span
                              className="exposure-bar-fill pos"
                              style={{
                                width: `${
                                  (row.runs / Math.max(...metrics.scenario_runs.map((r) => r.runs))) *
                                  100
                                }%`
                              }}
                            />
                          </span>
                          <span className="exposure-bar-value">{row.runs}</span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="muted">
                    No scenario runs recorded yet in this window. Dimensions are attached to new
                    requests only.
                  </p>
                )}

                <p className="ops-status-line">
                  {metrics.synthetic_excluded > 0
                    ? `${metrics.synthetic_excluded} pre-warm request(s) excluded · `
                    : ""}
                  {metrics.truncated ? `first ${metrics.entries_scanned} entries only · ` : ""}
                  history limited to {metrics.log_retention_days}d log retention
                </p>
              </>
            )}
          </section>
        ) : null}

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
                {status.environment} · {status.model_id} · prompt {status.prompt_version} ·{" "}
                {status.ready ? "ready" : "degraded"}
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
