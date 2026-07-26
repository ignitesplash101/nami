# Cost controls — preventing runaway Gemini spend

The deployed nami app is publicly invokable (`--allow-unauthenticated` on Cloud Run). This page documents why that is safe, and the additional GCP-side controls to harden it further.

---

## Cost-surface audit (code-side)

Every endpoint that calls Vertex AI / Gemini is gated as follows in [app/api/main.py](../app/api/main.py) and [app/api/security.py](../app/api/security.py):

| endpoint | visitor mode | admin mode | LLM cost per request |
|---|---|---|---|
| `POST /api/scenarios/run` | restricted to `SAMPLE_SCENARIOS` × `SAMPLE_PORTFOLIOS` only ([main.py:148–164](../app/api/main.py)) | free-text + custom portfolio + backdating allowed | ~$0.08 on cache miss; $0 on cache hit |
| `POST /api/scenarios/run-stream` | same gates via `_resolve_*` helpers | same as above | same |
| `POST /api/scenarios/adjust-shocks` | **403** ([main.py:348–349](../app/api/main.py)) | one Gemini call | ~$0.015 |
| `POST /api/scenarios/decompose` | **403** ([main.py:384–386](../app/api/main.py)) | 1 + 2^N − 1 Gemini calls (N=2..4) | ~$0.15–$0.80 (estimate) |
| `POST /api/saved-scenarios` and all Firestore endpoints | **403** ([main.py:408–410](../app/api/main.py)) | Firestore writes, no LLM | Firestore-only |
| `GET /api/portfolios/samples`, `/api/scenarios/samples`, `/api/health`, `/api/access`, `/api/meta`, `/api/docs/methodology`, `/api/portfolio/validate` | open | open | $0 (no LLM) |

**Visitor cost ceiling — the sample matrix is NOT the bound.** It is tempting to say: 4 sample scenarios × 4 sample portfolios = 16 combinations × ~$0.08 = a few dollars a week, done. That was this document's claim until 2026-07-26, and **it was wrong**. `_resolve_scenario_text` ([main.py](../app/api/main.py)) accepts *arbitrary* visitor scenario text before it ever checks the sample key — deliberately, per the Phase 17 design, and the endpoint's own 403 says so ("a sample scenario **or custom scenario text**"). A visitor can mint an unbounded number of distinct cache keys.

**The real ceiling is the money breakers**, not the sample matrix:

```
cost cap   $25 / day  ÷ ~$0.08 per cache-miss run  ≈ 310 paid runs / day
run cap    500 paid runs / day
```

so the **cost cap binds first**, at roughly $25/day (~$750/month worst case), plus a small overshoot equal to the number of simultaneously in-flight runs. Anything stronger than that has to come from the auth gates, not from arithmetic about samples.

The cache (GCS, 7-day TTL, [`app/data/cache.py`](../app/data/cache.py)) still absorbs identical requests at $0, and the daily **run cap** counts **paid runs only** — a cache hit makes zero model calls and is not charged against it. (Until Phase 36 the counter incremented on every request, so cached traffic could exhaust the cap and 429 legitimate free visitors at no saving.) Concurrent identical requests are also collapsed by a per-key single-flight, so a burst on one scenario computes once rather than N times.

**Standing cost: the daily pre-warm.** [`.github/workflows/prewarm.yml`](../.github/workflows/prewarm.yml) runs [`scripts/prewarm_samples.py`](../scripts/prewarm_samples.py) at 21:30 UTC on weekdays, warming every sample combination just after the 16:00 ET as-of rollover. Measured effect: a cold combination takes ~55s, a warm one ~0.4s. Cost is **~$1.30 per trading day (~$27/month)** and it is genuinely additional — on a day nobody visits a given combination, that combination's warm is wasted. Trim it with the workflow's `limit` input or by shrinking the sample sets.

**Admin cost ceiling**: not bounded by code. The admin passcode is the gate. If the passcode leaks, abuse is bounded only by Vertex AI quotas (see below).

---

## Defense-in-depth (GCP Console steps — user action)

Even with the above, two GCP-level controls add belt-and-braces protection.

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

Expected normal spend at this project's scale: a few dollars/month. A breach to $10 would mean ~400 LLM calls beyond cache hits — strong signal of admin-mode abuse, a logic bug, or a broken cache write path. Note the theoretical visitor ceiling above (~$28/month worst case) can alone cross the 50% threshold; if alerts fire without matching admin activity, check cache health first.

(The `gcloud billing budgets create` CLI requires JSON body parameters that the simple flag form doesn't accept; the Console form is faster and more reliable.)

### 2. Vertex AI request-quota cap (3 min)

Caps the number of Gemini requests per minute / per day at the project level. If hit, requests fail with `429 Too Many Requests` — billing never accumulates beyond the cap.

1. Open https://console.cloud.google.com/iam-admin/quotas?project=nami-497405
2. Filter: `Service: Vertex AI API`
3. Find the relevant quota for `gemini-3.6-flash` (typical name: `Generate content requests per minute per project per base model`). Quotas are **per base model** — an override set for `gemini-3.5-flash` does NOT cover `gemini-3.6-flash`; re-create it after a model upgrade.
4. Select → **EDIT QUOTAS** → request override → set a low limit (e.g. `60 per minute`, `5000 per day`)
5. Submit

Recommended starting caps (room for legitimate use, no room for runaway):
- Requests per minute: `60` (enough for streaming UI + a few simultaneous users)
- Requests per day: `1000` (a hard ~$27/day worst case at ~$0.027 per cache-miss-grade call — aligned with the in-app $25/day cost breaker)

If you ever legitimately need more, raise the cap from the same page in 30 seconds.

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

- **Gemini unit-price changes**: Google can change Gemini 3.6 Flash pricing unilaterally. The quota cap above bounds *units*, not *dollars per unit*. The in-app estimator's prices live in `app/config.py` (`PRICE_INPUT_PER_MTOK` / `PRICE_OUTPUT_PER_MTOK` overridable via env) and must be updated on repricing — on 2026-07-22 they were found stale at 2.5-Flash-era rates, under-counting real spend ~5×; they now match 3.6 Flash list prices and thinking tokens are booked at the output rate.
- **Cache infrastructure failure**: if the GCS bucket becomes unwritable, every request becomes a cache miss. The billing alert catches this within 24 hrs.
- **Side-channel cost**: yfinance is free but rate-limited; Firestore reads/writes are sub-cent at this scale; Cloud Run egress on free-tier-adjacent volumes. Negligible.

---

## Summary

| risk | mitigation | mitigated by |
|---|---|---|
| Anonymous visitor spam Gemini → $1000 bill | Visitor mode locked to 16 cached sample combinations | Code (auth gates + GCS cache) |
| Admin passcode leak | Rotate passcode in Secret Manager | Operator action |
| Logic bug bypasses gate | Monthly budget alert at $20 | GCP billing budget (Console) |
| Pricing change / cache outage | Vertex AI per-minute and per-day quota cap | GCP quotas (Console) |
