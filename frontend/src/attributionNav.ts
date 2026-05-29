import type { AttributionMethod } from "./types";

export interface AttributionOption {
  method: AttributionMethod;
  disabled: boolean;
}

/**
 * Roving-radiogroup navigation: given the ordered attribution options, the
 * current method, and a direction (+1 / -1), return the next ENABLED method,
 * wrapping around the ends. Disabled options are skipped. Returns `current`
 * unchanged when there are no enabled options or `current` isn't among them.
 */
export function nextEnabledMethod(
  options: AttributionOption[],
  current: AttributionMethod,
  direction: 1 | -1
): AttributionMethod {
  const enabled = options.filter((option) => !option.disabled);
  if (enabled.length === 0) return current;
  const idx = enabled.findIndex((option) => option.method === current);
  if (idx === -1) return current;
  const nextIdx = (idx + direction + enabled.length) % enabled.length;
  return enabled[nextIdx].method;
}
