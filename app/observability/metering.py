"""Paid-Gemini metering + daily budget breaker.

The budget is enforced at the ONE chokepoint every paid call routes through —
`GeminiClient._generate_content` — via a metered subclass. Each call reserves an
estimate against a Firestore-transactional daily doc BEFORE the model call and
reconciles to the actual `usage_metadata` after, so internal fan-out (retries,
decomposition subset reruns) and cache-miss-only spend are all counted, while a
cache hit (zero calls) costs nothing.

Reservation failures due to a real cap hit raise `BudgetExceededError` (→ HTTP
429). Failures due to store/infra errors fail OPEN (the call proceeds without a
reservation) so a Firestore blip can't take the whole service down — the per-IP
rate limiter and run cap remain as backstops.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime

from app.config import Config
from app.data.firestore_store import SavedScenarioStore
from app.llm.gemini_client import GeminiClient

# Nominal per-call reservation (tokens) used to estimate cost BEFORE the call,
# reconciled to actuals after. Deliberately generous so reservations don't
# under-shoot a large grounded call.
_RESERVE_TOKENS_IN = 8000
_RESERVE_TOKENS_OUT = 2000


class BudgetExceededError(Exception):
    """Raised when a paid call would exceed the daily cost or run cap (→ 429).

    Intentionally NOT a RuntimeError/ValueError so it is not swallowed by the
    endpoints' existing `except RuntimeError/ValueError` handlers.
    """


class RunCapExceededError(BudgetExceededError):
    """Daily run cap hit (vs the cost cap). MUST subclass `BudgetExceededError`
    so the endpoints' existing `except BudgetExceededError` handlers still catch
    it; the subclass only lets them emit a distinct machine-readable error code.
    """


@dataclass
class RunTelemetry:
    """Request-scoped accumulator for paid Gemini usage."""

    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    est_cost_usd: float = 0.0

    def record(self, *, tokens_in: int, tokens_out: int, cost: float) -> None:
        self.calls += 1
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.est_cost_usd += cost


def today_key() -> str:
    return datetime.now(UTC).date().isoformat()


def cost_usd(tokens_in: int, tokens_out: int, config: Config) -> float:
    return (
        tokens_in / 1_000_000 * config.price_input_per_mtok
        + tokens_out / 1_000_000 * config.price_output_per_mtok
    )


def _usage_tokens(response: object) -> tuple[int, int]:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return 0, 0
    tokens_in = int(getattr(meta, "prompt_token_count", 0) or 0)
    tokens_out = int(getattr(meta, "candidates_token_count", 0) or 0)
    return tokens_in, tokens_out


def enforce_run_cap(store: SavedScenarioStore, config: Config, day: str) -> None:
    """Increment today's run counter and reject once over the daily run cap.

    Best-effort: a store/infra error fails open (the cost breaker is the harder
    backstop). A real cap hit raises `BudgetExceededError`.
    """
    runs = 0
    with contextlib.suppress(Exception):
        runs = store.increment_daily_run(day)
    if runs and runs > config.daily_llm_run_cap:
        raise RunCapExceededError("Daily scenario run cap reached; try again tomorrow.")


class MeteredGeminiClient(GeminiClient):
    """GeminiClient that reserves/reconciles budget and records telemetry per call."""

    def __init__(
        self,
        config: Config,
        *,
        store: SavedScenarioStore,
        telemetry: RunTelemetry,
        day: str | None = None,
    ) -> None:
        super().__init__(config)
        self._config = config
        self._store = store
        self._telemetry = telemetry
        self._day = day or today_key()
        self._cap = config.daily_llm_cost_cap_usd
        self._estimate = cost_usd(_RESERVE_TOKENS_IN, _RESERVE_TOKENS_OUT, config)

    def _generate_content(self, *, contents: object, config: object) -> object:
        did_reserve = False
        try:
            did_reserve = self._store.reserve_budget(self._day, self._estimate, cap=self._cap)
            if not did_reserve:
                raise BudgetExceededError("Daily LLM budget cap reached; try again tomorrow.")
        except BudgetExceededError:
            raise
        except Exception:
            # Store/infra error — fail open, proceed without a reservation.
            did_reserve = False

        reserved_amt = self._estimate if did_reserve else 0.0
        try:
            response = super()._generate_content(contents=contents, config=config)
        except Exception:
            # Conservative reconcile: book the estimate so failed calls still count.
            with contextlib.suppress(Exception):
                self._store.settle_budget(
                    self._day,
                    reserved=reserved_amt,
                    actual=self._estimate,
                    tokens_in=0,
                    tokens_out=0,
                )
            self._telemetry.record(tokens_in=0, tokens_out=0, cost=self._estimate)
            raise

        tokens_in, tokens_out = _usage_tokens(response)
        actual = cost_usd(tokens_in, tokens_out, self._config)
        with contextlib.suppress(Exception):
            self._store.settle_budget(
                self._day,
                reserved=reserved_amt,
                actual=actual,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        self._telemetry.record(tokens_in=tokens_in, tokens_out=tokens_out, cost=actual)
        return response
