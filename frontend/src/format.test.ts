import { describe, expect, it } from "vitest";
import {
  formatDateTime,
  formatEvidence,
  formatFxRate,
  formatMarkPrice,
  formatShares,
  relativeTime,
  slugify
} from "./format";

describe("formatShares", () => {
  it("adds thousands separators and caps at 2 decimals", () => {
    expect(formatShares(12500)).toBe("12,500");
    expect(formatShares(1234.567)).toBe("1,234.57");
  });

  it("renders the em-dash placeholder for missing values", () => {
    expect(formatShares(null)).toBe("—");
    expect(formatShares(undefined)).toBe("—");
  });
});

describe("formatMarkPrice", () => {
  it("formats with an optional currency suffix", () => {
    expect(formatMarkPrice(189.3)).toBe("189.3");
    expect(formatMarkPrice(2750.5, "JPY")).toBe("2,750.5 JPY");
    expect(formatMarkPrice(null)).toBe("—");
  });
});

describe("formatFxRate", () => {
  it("renders 4 significant figures with the pair label", () => {
    expect(formatFxRate("JPY", 0.0064516)).toBe("JPY 0.006452");
  });
});

describe("relativeTime", () => {
  const now = new Date("2026-06-10T12:00:00Z").getTime();
  const iso = (msAgo: number) => new Date(now - msAgo).toISOString();

  it("buckets minutes, hours, and days with an injected now", () => {
    expect(relativeTime(iso(10_000), now)).toBe("just now");
    expect(relativeTime(iso(5 * 60_000), now)).toBe("5m ago");
    expect(relativeTime(iso(3 * 3_600_000), now)).toBe("3h ago");
    expect(relativeTime(iso(3 * 86_400_000), now)).toBe("3d ago");
  });

  it("falls back to a locale date beyond 30 days", () => {
    const old = iso(45 * 86_400_000);
    expect(relativeTime(old, now)).toBe(new Date(old).toLocaleDateString());
  });
});

describe("formatDateTime", () => {
  it("includes the date (history entries can span days)", () => {
    expect(formatDateTime("2026-06-10T14:32:00Z")).toMatch(/\w{3} \d{1,2}, \d{4}/);
  });
});

describe("formatEvidence", () => {
  it("fixes 4 decimals", () => {
    expect(formatEvidence(0.123449)).toBe("0.1234");
  });
});

describe("slugify", () => {
  it("lowercases, strips punctuation, and caps word count", () => {
    expect(slugify("China tariff escalation: 25% on tech!", 4)).toBe(
      "china-tariff-escalation-25"
    );
    expect(slugify("us_tech_growth")).toBe("us-tech-growth");
    expect(slugify("  trims  ---  edges  ")).toBe("trims-edges");
  });
});
