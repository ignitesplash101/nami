export type ResultOrigin = "live" | "saved" | null;

export function canEditAndRerun(origin: ResultOrigin): boolean {
  return origin === "saved";
}
