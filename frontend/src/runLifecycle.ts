/** Run lifecycle guard for streamed actions (run / decompose).
 *
 * `begin()` aborts any in-flight stream and hands back a sequence number +
 * AbortSignal; callers gate EVERY state write (progress frames, the final
 * result, catch, finally) on `isCurrent(seq)` so a stale stream can never
 * overwrite a newer run. `cancel()` aborts without invalidating the sequence —
 * the cancelled run's own catch/finally still apply (and surface kind
 * "cancelled", which the UI swallows).
 */

export interface RunHandle {
  seq: number;
  signal: AbortSignal;
}

export interface RunLifecycle {
  begin(): RunHandle;
  isCurrent(seq: number): boolean;
  cancel(): void;
}

export function createRunLifecycle(): RunLifecycle {
  let seq = 0;
  let controller: AbortController | null = null;
  return {
    begin() {
      controller?.abort();
      controller = new AbortController();
      seq += 1;
      return { seq, signal: controller.signal };
    },
    isCurrent(handleSeq: number) {
      return handleSeq === seq;
    },
    cancel() {
      controller?.abort();
    }
  };
}
