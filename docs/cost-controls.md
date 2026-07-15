# Cost controls — preventing runaway Gemini spend

The deployed nami app is publicly invokable (`--allow-unauthenticated` on Cloud Run). This page documents why that is safe, and the additional GCP-side controls to harden it further.

---

## Cost-surface audit (code-side)

Every endpoint that calls Vertex AI / Gemini is gated as follows in [app/api/main.py](../app/api/main.py) and [app/api/security.py](../app/api/security.py):

| endpoint | visitor mode | admin mode | LLM cost per request |
|---|---|---|---|
| `POST /api/scenarios/run` | restricted to `SAMPLE_SCENARIOS` × `SAMPLE_PORTFOLIOS` only | free-text + custom portfolio + backdating allowed | Legacy: ~3 Gemini calls; Quant V2: normally 2, up to 3 after one schema repair; $0 on cache hit |
| `POST /api/scenarios/run-stream` | same gates via `_resolve_*` helpers | same as above | same |
| `POST /api/scenarios/adjust-shocks` | **403** | Legacy only: one Gemini call; Quant V2 returns 422 | ~$0.0005 when available |
| `POST /api/scenarios/decompose` | **403** | Legacy only: 1 + 2^N − 1 Gemini calls (N=2..4); Quant V2 returns 422 | ~$0.005–$0.05 when available |
| `POST /api/saved-scenarios` and all Firestore endpoints | **403** ([main.py:408–410](../app/api/main.py)) | Firestore writes, no LLM | Firestore-only |
| `GET /api/portfolios/samples`, `/api/scenarios/samples`, `/api/health`, `/api/access`, `/api/meta`, `/api/docs/methodology`, `/api/portfolio/validate` | open | open | $0 (no LLM) |

**Visitor cost ceiling in the deployed default (`ENGINE_MODE=legacy`)**: 4 sample scenarios × 4 sample portfolios = **16 unique combinations**. The scenario cache key includes `effective_as_of`, which advances once per NYSE trading day, so each combination produces ~5 unique cache entries per week. Worst-case per-week spend from anonymous traffic, assuming infinite visitors:

```
16 combinations × 5 NYSE days × $0.003 per first miss = ~$0.24 / week
```

The cache (GCS, 7-day TTL, [`app/data/cache.py`](../app/data/cache.py)) absorbs all subsequent identical requests at $0. So the cost is bounded *regardless of visitor traffic volume* — a 1000-visitor day costs the same as a 1-visitor day after the cache warms.

If Quant V2 is promoted, its 3 horizons × 3 severity levels expand the visitor cache surface to at most 144 combinations per effective date. Quant V2 normally uses two Gemini calls (with at most one extra selector-repair call) and public-data caches, so operators must remeasure the per-miss cost before changing `ENGINE_MODE`. `shadow` deliberately runs both engines synchronously and can roughly double run latency and LLM spend; it is an evaluation mode, not the public default.

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

Expected normal spend at this project's scale: well under $1/month. A breach to $10 would mean ~3000 LLM calls beyond cache hits — strong signal of either admin-mode abuse or a logic bug.

(The `gcloud billing budgets create` CLI requires JSON body parameters that the simple flag form doesn't accept; the Console form is faster and more reliable.)

### 2. Vertex AI request-quota cap (3 min)

Caps the number of Gemini requests per minute / per day at the project level. If hit, requests fail with `429 Too Many Requests` — billing never accumulates beyond the cap.

1. Open https://console.cloud.google.com/iam-admin/quotas?project=nami-497405
2. Filter: `Service: Vertex AI API`
3. Find the relevant quota for `gemini-3.5-flash` (typical name: `Generate content requests per minute per project per base model`)
4. Select → **EDIT QUOTAS** → request override → set a low limit (e.g. `60 per minute`, `5000 per day`)
5. Submit

Recommended starting caps (room for legitimate use, no room for runaway):
- Requests per minute: `60` (enough for streaming UI + a few simultaneous users)
- Requests per day: `5000` (a hard ~$15/day worst case if all are cache-miss-grade scenario runs)

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

- **Gemini unit-price changes**: Google can change Gemini 3.5 Flash pricing unilaterally. The quota cap above bounds *units*, not *dollars per unit*.
- **Cache infrastructure failure**: if the GCS bucket becomes unwritable, every request becomes a cache miss. The billing alert catches this within 24 hrs.
- **Side-channel cost**: yfinance is free but rate-limited; Firestore reads/writes are sub-cent at this scale; Cloud Run egress on free-tier-adjacent volumes. Negligible.

---

## Summary

| risk | mitigation | mitigated by |
|---|---|---|
| Anonymous visitor spam Gemini → $1000 bill | Default legacy mode is locked to 16 cached sample combinations | Code (auth gates + GCS cache) |
| Admin passcode leak | Rotate passcode in Secret Manager | Operator action |
| Logic bug bypasses gate | Monthly budget alert at $20 | GCP billing budget (Console) |
| Pricing change / cache outage | Vertex AI per-minute and per-day quota cap | GCP quotas (Console) |
