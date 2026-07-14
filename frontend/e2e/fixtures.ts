import { expect, type Page, type Route } from "@playwright/test";

export const viewports = [
  { width: 320, height: 740 },
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1080, height: 800 },
  { width: 1440, height: 900 },
  { width: 1600, height: 1000 },
  { width: 1920, height: 1080 }
] as const;

const visitorAccess = {
  access_mode: "visitor",
  admin_available: true,
  latest_market_date: "2026-07-13",
  sample_weights_as_of: "2026-06-30",
  permissions: {
    custom_portfolio: false,
    free_text_scenario: false,
    narrative_decomposition: false
  }
};

const adminAccess = {
  ...visitorAccess,
  access_mode: "admin",
  permissions: {
    custom_portfolio: true,
    free_text_scenario: true,
    narrative_decomposition: true
  }
};

const portfolios = [
  {
    key: "us_tech_growth",
    name: "US tech growth",
    description: "Concentrated growth leaders",
    holdings: { AAPL: 0.6, MSFT: 0.4 },
    benchmark: "SPY"
  }
];

const scenarios = [
  { key: "china_tariffs", name: "Tariff escalation", text: "A sharp tariff escalation" },
  { key: "rates_higher", name: "Rates stay higher", text: "Policy rates remain restrictive" },
  { key: "credit_freeze", name: "Credit freeze", text: "Credit markets seize up" },
  { key: "oil_spike", name: "Oil spike", text: "Oil prices jump abruptly" }
];

const factors = [
  {
    key: "SPY",
    ticker: "SPY",
    group: "market",
    short_label: "US market",
    display_name: "US market (SPY)",
    description: "Broad US equity market"
  }
];

export const scenarioEnvelope = {
  result: {
    scenario_text: "A sharp tariff escalation",
    market_date: "2026-07-13",
    portfolio_key: "us_tech_growth",
    portfolio_name: "US tech growth",
    portfolio_holdings: { AAPL: 0.6, MSFT: 0.4 },
    analogs_selected: [],
    factor_shocks: [{ factor: "SPY", shock: -0.1, reasoning: "Broad risk repricing" }],
    periphery_shocks: [],
    narrative: "Risk assets sell off as the policy shock reaches earnings expectations.",
    citations: [],
    factor_envelope: { SPY: { p10: -0.18, p90: -0.04, median: -0.09, count: 5 } },
    portfolio_pnl: {
      total_pnl: -0.08,
      by_factor_naive: { SPY: -0.08 },
      by_factor_conditional_shapley: { SPY: -0.08 },
      by_factor_conditional_shapley_explicit: { SPY: -0.08 },
      by_factor_conditional_shapley_grouped: { SPY: -0.08 },
      by_ticker_factor: { AAPL: -0.05, MSFT: -0.03 },
      by_ticker_periphery: { AAPL: 0, MSFT: 0 },
      by_ticker_total: { AAPL: -0.05, MSFT: -0.03 }
    },
    narrative_shapley: null,
    adjustment_history: [],
    requested_as_of_date: "2026-07-13",
    narrative_mode: "grounded",
    selected_event_ids: [],
    severity_ladder: {
      worst_pnl: -0.14,
      base_pnl: -0.08,
      best_pnl: -0.03,
      n_banded: 1,
      n_held: 0
    },
    pnl_uncertainty: {
      band_1sigma: 0.02,
      portfolio_idio_vol_weekly: 0.02,
      horizon_weeks: 1
    },
    benchmark_ticker: "SPY",
    active_return: -0.01
  },
  analog_events: {},
  cache_key: "fixture-cache-key",
  reproducibility: {
    model_id: "fixture-model",
    prompt_version: "fixture-prompt",
    factor_universe_version: "fixture-factors",
    events_version: "fixture-events",
    requested_as_of_date: "2026-07-13",
    effective_as_of_date: "2026-07-13",
    narrative_mode: "grounded",
    beta_lookback_weeks: 156,
    ridge_alpha: 0.1,
    regression_spec: "fixture-regression",
    selected_event_ids: [],
    portfolio_holdings: { AAPL: 0.6, MSFT: 0.4 },
    portfolio_key: "us_tech_growth",
    market_data_source: "yfinance",
    nami_engine_version: "fixture-engine"
  }
};

type MockOptions = {
  admin?: boolean;
  failFirstAccessTransport?: boolean;
};

const localHosts = new Set(["127.0.0.1", "localhost"]);
const handledExternalHosts = new Set(["fonts.googleapis.com", "fonts.gstatic.com"]);

function isExternalHttpRequest(requestUrl: string) {
  const url = new URL(requestUrl);
  return (url.protocol === "http:" || url.protocol === "https:") && !localHosts.has(url.hostname);
}

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body)
  });
}

export async function installApiMocks(page: Page, options: MockOptions = {}) {
  const unexpected: string[] = [];
  const handledExternal: string[] = [];
  const unexpectedExternal: string[] = [];
  const escapedExternal: string[] = [];
  let accessAttempts = 0;

  page.on("requestfinished", (request) => {
    if (isExternalHttpRequest(request.url())) {
      escapedExternal.push(`${request.method()} ${request.url()}`);
    }
  });

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;

    if (isExternalHttpRequest(request.url())) {
      const externalKey = `${request.method()} ${request.url()}`;
      if (handledExternalHosts.has(url.hostname)) {
        handledExternal.push(externalKey);
      } else {
        unexpectedExternal.push(externalKey);
      }
      await route.abort("blockedbyclient");
      return;
    }

    if (url.pathname !== "/api" && !url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }

    if (key === "GET /api/access") {
      accessAttempts += 1;
      if (options.failFirstAccessTransport && accessAttempts === 1) {
        await route.abort("connectionrefused");
        return;
      }
      await json(route, options.admin ? adminAccess : visitorAccess);
      return;
    }
    if (key === "GET /api/portfolios/samples") return void (await json(route, portfolios));
    if (key === "GET /api/scenarios/samples") return void (await json(route, scenarios));
    if (key === "GET /api/factors") return void (await json(route, factors));
    if (key === "GET /api/docs/methodology") {
      return void (await route.fulfill({ status: 200, contentType: "text/plain", body: "# Methodology" }));
    }
    if (key === "POST /api/scenarios/run-stream") {
      const body = [
        { stage: "cache_check", status: "start" },
        { stage: "cache_check", status: "done" },
        { stage: "done", result: scenarioEnvelope }
      ]
        .map((event) => `data: ${JSON.stringify(event)}\n\n`)
        .join("");
      return void (await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        headers: { "x-request-id": "fixture-request" },
        body
      }));
    }
    if (key === "GET /api/portfolios/ticker-metadata") {
      return void (await json(route, {
        ticker_meta: {
          AAPL: { sector: "Technology", country: "US" },
          MSFT: { sector: "Technology", country: "US" }
        }
      }));
    }
    if (key === "GET /api/saved-scenarios") return void (await json(route, []));
    if (key === "GET /api/portfolios") return void (await json(route, []));
    if (key === "GET /api/usage") {
      return void (await json(route, {
        day: "2026-07-14",
        runs: 1,
        calls: 3,
        tokens_in: 100,
        tokens_out: 50,
        spent_usd: 0.01,
        reserved_usd: 0,
        cost_cap_usd: 5,
        run_cap: 100
      }));
    }
    if (key === "GET /api/status") {
      return void (await json(route, {
        service: "nami",
        nami_engine_version: "fixture-engine",
        prompt_version: "fixture-prompt",
        model_id: "fixture-model",
        environment: "test",
        ready: true,
        disclaimer: "fixture",
        rate_limits: {},
        daily_cost_cap_usd: 5,
        daily_run_cap: 100,
        runs_today: 1,
        est_cost_today_usd: 0.01
      }));
    }
    if (key === "GET /api/audit") return void (await json(route, []));

    unexpected.push(key);
    await route.abort("blockedbyclient");
  });

  return {
    unexpected,
    handledExternal,
    unexpectedExternal,
    escapedExternal,
    accessAttempts: () => accessAttempts
  };
}

type InstalledApiMocks = Awaited<ReturnType<typeof installApiMocks>>;

export function expectCleanNetworkPolicy(api: InstalledApiMocks) {
  expect(api.unexpected, "unexpected local API requests").toEqual([]);
  expect(api.unexpectedExternal, "unexpected external requests").toEqual([]);
  expect(api.escapedExternal, "external requests that escaped interception").toEqual([]);
  expect(
    api.handledExternal.some((request) => request.includes("https://fonts.googleapis.com/")),
    "the declared Google Fonts stylesheet should be handled by the deterministic network policy"
  ).toBe(true);
}

export async function setPersistedTheme(page: Page, theme: "dark" | "light") {
  await page.addInitScript((choice) => localStorage.setItem("nami-theme", choice), theme);
}

export async function expectNoDocumentOverflow(page: Page) {
  return page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    offenders: Array.from(document.querySelectorAll("body *"))
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName.toLowerCase(),
          className: element.getAttribute("class") ?? "",
          text: element.textContent?.trim().slice(0, 80) ?? "",
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width)
        };
      })
      .filter(({ left, right }) => left < -1 || right > document.documentElement.clientWidth + 1)
      .slice(0, 12)
  }));
}

export async function compactControlViolations(page: Page) {
  return page.locator(
    ".primary-button:visible, .ghost-button:visible, .methodology-btn:visible, " +
      "[role=tab]:visible, .scenario-chips .chip:visible, input:visible, select:visible, textarea:visible"
  ).evaluateAll((elements) =>
    elements
      .map((element) => ({
        label:
          element.getAttribute("aria-label") ||
          element.textContent?.trim() ||
          element.tagName.toLowerCase(),
        height: element.getBoundingClientRect().height
      }))
      .filter(({ height }) => height < 43.5)
  );
}
