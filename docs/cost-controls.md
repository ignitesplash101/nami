# Cost controls — preventing runaway Gemini spend

The deployed nami app is publicly invokable (`--allow-unauthenticated` on Cloud Run). This page documents why that is safe, and the additional GCP-side controls to harden it further.

---

## Cost-surface audit (code-side)

Every endpoint that calls Vertex AI / Gemini is gated as follows in [app/api/main.py](../app/api/main.py) and [app/api/security.py](../app/api/security.py):

| endpoint | visitor mode | admin mode | LLM cost per request |
|---|---|---|---|
| `POST /api/scenarios/run` | sample portfolios only, with a sample scenario OR custom scenario text (`_resolve_scenario_text` / `_resolve_portfolio` in [main.py](../app/api/main.py)); custom holdings and backdating are 403 | free-text + custom portfolio + backdating allowed | ~$0.08 on cache miss; $0 on cache hit |
| `POST /api/scenarios/run-stream` | same gates via `_resolve_*` helpers | same as above | same |
| `POST /api/scenarios/adjust-shocks` | **403** ([main.py:348–349](../app/api/main.py)) | one Gemini call | ~$0.015 |
| `POST /api/scenarios/decompose` | **403** ([main.py:384–386](../app/api/main.py)) | 1 + 2^N − 1 Gemini calls (N=2..4) | ~$0.15–$0.80 (estimate) |
| `POST /api/saved-scenarios` and all Firestore endpoints | **403** ([main.py:408–410](../app/api/main.py)) | Firestore writes, no LLM | Firestore-only |
| `GET /api/portfolios/samples`, `/api/scenarios/samples`, `/api/health`, `/api/access`, `/api/meta`, `/api/docs/methodology`, `/api/portfolio/validate` | open | open | $0 (no LLM) |

The LLM figures above are conservative budget-breaker estimates using the
$1.50/$7.50 post-promotion rates and measured historical token usage. Gemini 3.8
Flash is billed at $0.75/$3.75 through 2026-12-31, so equal token usage costs about
half as much during the introductory period. The breaker deliberately keeps the
higher rates so it does not begin under-counting when the promotion expires.

**Visitor cost ceiling — the sample matrix is NOT the bound.** It is tempting to say: 4 sample scenarios × 4 sample portfolios = 16 combinations × ~$0.08 = a few dollars a week, done. That was this document's claim until 2026-07-26, and **it was wrong**. `_resolve_scenario_text` ([main.py](../app/api/main.py)) accepts *arbitrary* visitor scenario text before it ever checks the sample key — deliberately, per the Phase 17 design, and the endpoint's own 403 says so ("a sample scenario **or custom scenario text**"). A visitor can mint an unbounded number of distinct cache keys.

**The real ceiling is the money breakers**, not the sample matrix:

```
cost cap   $25 / day  ÷ ~$0.08 per cache-miss run  ≈ 310 paid runs / day
run cap    500 paid runs / day
```

so the **cost cap binds first**, at roughly $25/day (~$750/month worst case), plus a small overshoot equal to the number of simultaneously in-flight runs. Anything stronger than that has to come from the auth gates, not from arithmetic about samples.

The cache (GCS, 7-day TTL, [`app/data/cache.py`](../app/data/cache.py)) still absorbs identical requests at $0, and the daily **run cap** counts **paid runs only** — a cache hit makes zero model calls and is not charged against it. (Until Phase 36 the counter incremented on every request, so cached traffic could exhaust the cap and 429 legitimate free visitors at no saving.) Concurrent identical requests are also collapsed by a per-key single-flight, so a burst on one scenario computes once rather than N times.

**Standing cost: the daily pre-warm.** [`.github/workflows/prewarm.yml`](../.github/workflows/prewarm.yml) runs [`scripts/prewarm_samples.py`](../scripts/prewarm_samples.py) at 21:30 UTC on weekdays, warming every sample combination just after the 16:00 ET as-of rollover. Measured effect: a cold combination takes ~55s, a warm one ~0.4s. Cost is **~$1.30 per trading day (~$27/month)** and it is genuinely additional — on a day nobody visits a given combination, that combination's warm is wasted. Trim it with the workflow's `limit` input or by shrinking the sample sets.

**Admin cost ceiling**: admin calls use the same paid-run and estimated-cost breakers.
The passcode expands access to arbitrary books, adjustments, and multi-call theme
sensitivity, so a leak can consume that daily allowance much faster than visitor traffic.
Rotate a leaked passcode immediately; the breaker and billing alerts are the backstops.

---

## Defense-in-depth (GCP Console steps — user action)

The billing alert below adds an independent fire alarm. Vertex's current throughput
model is documented separately because it is not an editable spend cap.

### 1. Monthly billing budget with email alerts (2 min)

This sends an email when monthly project spend crosses thresholds. It does **not** auto-shut-down — Google does not offer hard billing caps — but it is the standard fire alarm.

1. Open https://console.cloud.google.com/billing/budgets
2. **CREATE BUDGET**
3. Name: `nami-monthly-cap` · Time range: `Monthly` · Projects: `nami-497405`
4. Services: All (or filter to Vertex AI + Cloud Run + Firestore + Cloud Storage)
5. Budget amount: `Specified amount` · `$20` USD
6. Thresholds: `50%`, `90%`, `100%` (actual) and `100%` (forecast)
7. Email alerts: check "Email alerts to billing admins and users"
8. **FINISH**

Expected model spend with the full weekday pre-warm is roughly $14/month during the
Gemini 3.8 Flash introductory period, or roughly $27/month at post-promotion rates,
before additional admin use. A sharp increase beyond that baseline is a signal of
abuse, a logic bug, or a broken cache write path; if alerts fire without matching
admin activity, check cache health first.

(The `gcloud billing budgets create` CLI requires JSON body parameters that the simple flag form doesn't accept; the Console form is faster and more reliable.)

### 2. Vertex AI Dynamic Shared Quota (not a spend cap)

Gemini 3.8 Flash pay-as-you-go uses
[Dynamic Shared Quota](https://cloud.google.com/vertex-ai/generative-ai/docs/resources/throughput-quota),
which has no predefined per-model request limit to lower in the Quotas console. The
Service Usage API likewise exposes no `gemini-3.8-flash` quota bucket for this project
(verified 2026-09-03). A `429 Resource Exhausted` response means shared capacity is
temporarily busy; it is not evidence that a project-owned daily cap stopped spend.

Do not describe a legacy `Generate content requests per minute per project per base
model` override as protection for 3.8. The enforceable spend controls for this deployment
are the in-app daily breaker, authentication gates, cache/single-flight behavior, and the
billing alert above. Workloads that require reserved capacity can evaluate Provisioned
Throughput, but that is a capacity purchase rather than a hard billing ceiling.

### 3. Admin-passcode hygiene

The passcode is in Secret Manager (`nami-passcode:latest`). To rotate:

```bash
echo -n 'new-passcode' | gcloud secrets versions add nami-passcode --data-file=-
gcloud run services update nami --region=asia-northeast1 \
    --update-secrets=PASSCODE=nami-passcode:latest
```

Cloud Run will roll the revision and existing admin cookies will be invalidated automatically — `set_admin_cookie` in [app/api/security.py](../app/api/security.py) signs with the current passcode, so old cookies fail signature verification.

---

## What is NOT mitigated

- **Gemini unit-price changes**: Google can change Gemini 3.8 Flash pricing unilaterally. Dynamic Shared Quota does not bound units or dollars. The in-app estimator's prices live in `app/config.py` (`PRICE_INPUT_PER_MTOK` / `PRICE_OUTPUT_PER_MTOK` overridable via env). They intentionally use the $1.50/$7.50 rates that begin after the introductory period ends on 2026-12-31; thinking tokens are booked at the output rate. Re-check both defaults whenever Google reprices the model.
- **Cache infrastructure failure**: if the GCS bucket becomes unwritable, every request becomes a cache miss. The billing alert catches this within 24 hrs.
- **Side-channel cost**: yfinance is free but rate-limited; Firestore reads/writes are sub-cent at this scale; Cloud Run egress on free-tier-adjacent volumes. Negligible.

---

## Summary

| risk | mitigation | mitigated by |
|---|---|---|
| Anonymous visitor spam Gemini → $1000 bill | Paid-run and estimated-cost breakers cap daily exposure | Code (budget gates + GCS cache) |
| Admin passcode leak | Rotate passcode in Secret Manager | Operator action |
| Logic bug bypasses gate | Monthly budget alert at $20 | GCP billing budget (Console) |
| Pricing change / cache outage | Conservative in-app cost breaker plus billing alerts | Code + GCP Billing |
