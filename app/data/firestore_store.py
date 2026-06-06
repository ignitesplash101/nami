"""Firestore wrapper for saved analytics (scenarios + dated portfolios).

Mirrors the `CacheProtocol` ergonomics from `app/data/cache.py` for the simple
get/put paths and adds list/delete for queries. Records are stored as
Pydantic-model `.model_dump(mode='json')` payloads.

Firestore document size limit is 1 MB. We enforce a safety margin of 900 KB
on saves; oversized records raise `ValueError` rather than silently truncating
or splitting (v1 design choice — observed payloads are << 100 KB).
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any, Protocol

from app.api.schemas import (
    PortfolioSnapshotRecord,
    SavedPortfolioRecord,
    SavedScenarioListItem,
    SavedScenarioRecord,
)

# Safety margin under Firestore's 1 MB document limit. Saves above this threshold
# fail loudly so a future fat-payload regression is visible rather than silent.
MAX_FIRESTORE_DOC_BYTES = 900_000


class SavedScenarioStore(Protocol):
    """Minimal protocol so tests can inject `InMemoryFirestoreStore`."""

    def save_scenario(self, record: SavedScenarioRecord) -> str:
        ...

    def get_scenario(self, scenario_id: str) -> SavedScenarioRecord | None:
        ...

    def list_scenarios(
        self, *, tag: str | None = None, limit: int = 50
    ) -> list[SavedScenarioListItem]:
        ...

    def delete_scenario(self, scenario_id: str) -> None:
        ...

    def save_portfolio(self, record: SavedPortfolioRecord) -> str:
        ...

    def get_portfolio(self, portfolio_id: str) -> SavedPortfolioRecord | None:
        ...

    def list_portfolios(self) -> list[SavedPortfolioRecord]:
        ...

    def save_snapshot(self, portfolio_id: str, record: PortfolioSnapshotRecord) -> str:
        ...

    def get_snapshot(self, portfolio_id: str, snapshot_id: str) -> PortfolioSnapshotRecord | None:
        ...

    def list_snapshots(self, portfolio_id: str) -> list[PortfolioSnapshotRecord]:
        ...

    # --- Operational counters (transactional) ---

    def reserve_budget(self, day: str, amount: float, *, cap: float) -> bool:
        ...

    def settle_budget(
        self, day: str, *, reserved: float, actual: float, tokens_in: int, tokens_out: int
    ) -> None:
        ...

    def increment_daily_run(self, day: str) -> int:
        ...

    def usage_daily(self, day: str) -> dict[str, float]:
        ...

    def unlock_failure_count(self, key: str, *, window_seconds: int) -> int:
        ...

    def record_failed_unlock(self, key: str, *, window_seconds: int) -> int:
        ...

    def clear_unlock_failures(self, key: str) -> None:
        ...

    # --- Audit + data governance ---

    def record_audit(
        self,
        *,
        action: str,
        target_type: str,
        target_id: str | None = None,
        request_id: str | None = None,
        ip_hash: str | None = None,
    ) -> None:
        ...

    def list_audit(self, *, limit: int = 100) -> list[dict[str, Any]]:
        ...

    def export_all(self) -> dict[str, Any]:
        ...

    def purge_all(self) -> dict[str, int]:
        ...


def _payload_size_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, default=str).encode("utf-8"))


def _window_expired(window_start: Any, window_seconds: int) -> bool:
    """True if `window_start` (a datetime, possibly Firestore-naive) is older than
    `window_seconds`, so the throttle window should reset."""
    if window_start is None:
        return True
    if not isinstance(window_start, datetime):
        return True
    start = window_start if window_start.tzinfo else window_start.replace(tzinfo=UTC)
    return (utcnow() - start).total_seconds() > window_seconds


def _to_list_item(rec: SavedScenarioRecord) -> SavedScenarioListItem:
    return SavedScenarioListItem(
        id=rec.id,
        name=rec.name,
        tags=list(rec.tags),
        created_at=rec.created_at,
        owner_label=rec.owner_label,
        portfolio_name=rec.portfolio_name,
        portfolio_key=rec.portfolio_key,
        requested_as_of_date=rec.reproducibility.requested_as_of_date,
        effective_as_of_date=rec.reproducibility.effective_as_of_date,
        narrative_mode=rec.reproducibility.narrative_mode,
        total_pnl=rec.result.portfolio_pnl.total_pnl,
        portfolio_nav=rec.result.portfolio_nav,
    )


class FirestoreStore:
    """Concrete Firestore implementation. Created lazily on first use."""

    _SCENARIOS = "saved_scenarios"
    _PORTFOLIOS = "portfolios"
    _SNAPSHOTS = "snapshots"
    _USAGE = "usage_daily"
    _THROTTLE = "auth_throttle"
    _AUDIT = "audit_log"
    _BATCH_LIMIT = 450  # under Firestore's 500-op batch ceiling

    def __init__(self, project_id: str, *, client: Any = None) -> None:
        if client is None:
            from google.cloud import firestore  # local import; optional dep at runtime

            client = firestore.Client(project=project_id)
        self._client = client

    # --- Saved scenarios ---

    def save_scenario(self, record: SavedScenarioRecord) -> str:
        payload = record.model_dump(mode="json", exclude={"id"})
        size = _payload_size_bytes(payload)
        if size > MAX_FIRESTORE_DOC_BYTES:
            raise ValueError(
                f"Saved scenario payload is {size} bytes; exceeds Firestore "
                f"document safety margin of {MAX_FIRESTORE_DOC_BYTES}. v1 does "
                f"not split large payloads to GCS."
            )
        doc_ref = self._client.collection(self._SCENARIOS).document()
        doc_ref.set(payload)
        return doc_ref.id

    def get_scenario(self, scenario_id: str) -> SavedScenarioRecord | None:
        snap = self._client.collection(self._SCENARIOS).document(scenario_id).get()
        if not snap.exists:
            return None
        return SavedScenarioRecord.model_validate({**snap.to_dict(), "id": snap.id})

    def list_scenarios(
        self, *, tag: str | None = None, limit: int = 50
    ) -> list[SavedScenarioListItem]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self._client.collection(self._SCENARIOS)
        if tag is not None:
            query = query.where(filter=FieldFilter("tags", "array_contains", tag))
        query = query.order_by("created_at", direction="DESCENDING").limit(limit)
        try:
            docs = list(query.stream())
        except Exception as exc:  # noqa: BLE001 — surface a clearer message for missing index
            msg = str(exc)
            if "requires an index" in msg.lower() or "no matching index" in msg.lower():
                raise RuntimeError(
                    "Firestore composite index missing for saved_scenarios "
                    "(tags array_contains + created_at DESC). Create via:\n"
                    "  gcloud firestore indexes composite create \\\n"
                    "    --collection-group=saved_scenarios \\\n"
                    "    --field-config=field-path=tags,array-config=contains \\\n"
                    "    --field-config=field-path=created_at,order=descending"
                ) from exc
            raise
        items: list[SavedScenarioListItem] = []
        for snap in docs:
            try:
                record = SavedScenarioRecord.model_validate({**snap.to_dict(), "id": snap.id})
                items.append(_to_list_item(record))
            except Exception:  # noqa: BLE001 — skip malformed records, don't fail the list
                continue
        return items

    def delete_scenario(self, scenario_id: str) -> None:
        self._client.collection(self._SCENARIOS).document(scenario_id).delete()

    # --- Portfolios + snapshots ---

    def save_portfolio(self, record: SavedPortfolioRecord) -> str:
        payload = record.model_dump(mode="json", exclude={"id"})
        doc_ref = self._client.collection(self._PORTFOLIOS).document()
        doc_ref.set(payload)
        return doc_ref.id

    def get_portfolio(self, portfolio_id: str) -> SavedPortfolioRecord | None:
        snap = self._client.collection(self._PORTFOLIOS).document(portfolio_id).get()
        if not snap.exists:
            return None
        return SavedPortfolioRecord.model_validate({**snap.to_dict(), "id": snap.id})

    def list_portfolios(self) -> list[SavedPortfolioRecord]:
        query = (
            self._client.collection(self._PORTFOLIOS)
            .order_by("created_at", direction="DESCENDING")
            .limit(200)
        )
        return [
            SavedPortfolioRecord.model_validate({**snap.to_dict(), "id": snap.id})
            for snap in query.stream()
        ]

    def save_snapshot(self, portfolio_id: str, record: PortfolioSnapshotRecord) -> str:
        payload = record.model_dump(mode="json", exclude={"id"})
        doc_ref = (
            self._client.collection(self._PORTFOLIOS)
            .document(portfolio_id)
            .collection(self._SNAPSHOTS)
            .document()
        )
        doc_ref.set(payload)
        return doc_ref.id

    def get_snapshot(self, portfolio_id: str, snapshot_id: str) -> PortfolioSnapshotRecord | None:
        snap = (
            self._client.collection(self._PORTFOLIOS)
            .document(portfolio_id)
            .collection(self._SNAPSHOTS)
            .document(snapshot_id)
            .get()
        )
        if not snap.exists:
            return None
        return PortfolioSnapshotRecord.model_validate(
            {**snap.to_dict(), "id": snap.id, "portfolio_id": portfolio_id}
        )

    def list_snapshots(self, portfolio_id: str) -> list[PortfolioSnapshotRecord]:
        query = (
            self._client.collection(self._PORTFOLIOS)
            .document(portfolio_id)
            .collection(self._SNAPSHOTS)
            .order_by("as_of_date", direction="DESCENDING")
            .limit(500)
        )
        return [
            PortfolioSnapshotRecord.model_validate(
                {**snap.to_dict(), "id": snap.id, "portfolio_id": portfolio_id}
            )
            for snap in query.stream()
        ]

    # --- Operational counters (transactional) ---

    def reserve_budget(self, day: str, amount: float, *, cap: float) -> bool:
        """Atomically check the day's (spent + reserved) against `cap` and, if it
        fits, add `amount` to the reserved pool. Returns False (no reservation) if
        it would exceed the cap. The transaction is the authoritative gate against
        concurrent overspend."""
        from google.cloud import firestore

        ref = self._client.collection(self._USAGE).document(day)

        @firestore.transactional
        def _txn(transaction: Any) -> bool:
            snap = ref.get(transaction=transaction)
            data = snap.to_dict() if snap.exists else {}
            spent = float(data.get("spent", 0.0))
            reserved = float(data.get("reserved", 0.0))
            if spent + reserved + amount > cap:
                return False
            transaction.set(ref, {"reserved": reserved + amount}, merge=True)
            return True

        return _txn(self._client.transaction())

    def settle_budget(
        self, day: str, *, reserved: float, actual: float, tokens_in: int, tokens_out: int
    ) -> None:
        """Reconcile a prior reservation: release `reserved`, book `actual` spend,
        and accumulate token + run counters."""
        from google.cloud import firestore

        ref = self._client.collection(self._USAGE).document(day)

        @firestore.transactional
        def _txn(transaction: Any) -> None:
            snap = ref.get(transaction=transaction)
            data = snap.to_dict() if snap.exists else {}
            transaction.set(
                ref,
                {
                    "reserved": max(0.0, float(data.get("reserved", 0.0)) - reserved),
                    "spent": float(data.get("spent", 0.0)) + actual,
                    "tokens_in": int(data.get("tokens_in", 0)) + tokens_in,
                    "tokens_out": int(data.get("tokens_out", 0)) + tokens_out,
                    "calls": int(data.get("calls", 0)) + 1,
                },
                merge=True,
            )

        _txn(self._client.transaction())

    def increment_daily_run(self, day: str) -> int:
        from google.cloud import firestore

        ref = self._client.collection(self._USAGE).document(day)

        @firestore.transactional
        def _txn(transaction: Any) -> int:
            snap = ref.get(transaction=transaction)
            data = snap.to_dict() if snap.exists else {}
            runs = int(data.get("runs", 0)) + 1
            transaction.set(ref, {"runs": runs}, merge=True)
            return runs

        return _txn(self._client.transaction())

    def usage_daily(self, day: str) -> dict[str, float]:
        snap = self._client.collection(self._USAGE).document(day).get()
        return snap.to_dict() if snap.exists else {}

    def unlock_failure_count(self, key: str, *, window_seconds: int) -> int:
        snap = self._client.collection(self._THROTTLE).document(key).get()
        if not snap.exists:
            return 0
        data = snap.to_dict()
        if _window_expired(data.get("window_start"), window_seconds):
            return 0
        return int(data.get("count", 0))

    def record_failed_unlock(self, key: str, *, window_seconds: int) -> int:
        from google.cloud import firestore

        ref = self._client.collection(self._THROTTLE).document(key)

        @firestore.transactional
        def _txn(transaction: Any) -> int:
            snap = ref.get(transaction=transaction)
            data = snap.to_dict() if snap.exists else {}
            now = utcnow()
            if not data or _window_expired(data.get("window_start"), window_seconds):
                transaction.set(ref, {"count": 1, "window_start": now})
                return 1
            new_count = int(data.get("count", 0)) + 1
            transaction.set(ref, {"count": new_count}, merge=True)
            return new_count

        return _txn(self._client.transaction())

    def clear_unlock_failures(self, key: str) -> None:
        self._client.collection(self._THROTTLE).document(key).delete()

    # --- Audit + data governance ---

    def record_audit(
        self,
        *,
        action: str,
        target_type: str,
        target_id: str | None = None,
        request_id: str | None = None,
        ip_hash: str | None = None,
    ) -> None:
        self._client.collection(self._AUDIT).document().set(
            {
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "request_id": request_id,
                "ip_hash": ip_hash,
                "at": utcnow(),
            }
        )

    def list_audit(self, *, limit: int = 100) -> list[dict[str, Any]]:
        query = (
            self._client.collection(self._AUDIT).order_by("at", direction="DESCENDING").limit(limit)
        )
        return [snap.to_dict() for snap in query.stream()]

    def export_all(self) -> dict[str, Any]:
        scenarios = [
            {**snap.to_dict(), "id": snap.id}
            for snap in self._client.collection(self._SCENARIOS).stream()
        ]
        portfolios = []
        for psnap in self._client.collection(self._PORTFOLIOS).stream():
            snaps = [
                {**s.to_dict(), "id": s.id}
                for s in self._client.collection(self._PORTFOLIOS)
                .document(psnap.id)
                .collection(self._SNAPSHOTS)
                .stream()
            ]
            portfolios.append({**psnap.to_dict(), "id": psnap.id, "snapshots": snaps})
        return {"scenarios": scenarios, "portfolios": portfolios}

    def purge_all(self) -> dict[str, int]:
        """Delete all saved scenarios + portfolios (and their snapshot
        subcollections). Does NOT touch `audit_log` — the trail survives a purge.
        """
        counts = {"scenarios": 0, "portfolios": 0, "snapshots": 0}
        batch = self._client.batch()
        ops = 0

        def _flush() -> None:
            nonlocal batch, ops
            if ops:
                batch.commit()
                batch = self._client.batch()
                ops = 0

        for snap in self._client.collection(self._SCENARIOS).stream():
            batch.delete(snap.reference)
            counts["scenarios"] += 1
            ops += 1
            if ops >= self._BATCH_LIMIT:
                _flush()

        for psnap in self._client.collection(self._PORTFOLIOS).stream():
            subcol = (
                self._client.collection(self._PORTFOLIOS)
                .document(psnap.id)
                .collection(self._SNAPSHOTS)
            )
            for s in subcol.stream():
                batch.delete(s.reference)
                counts["snapshots"] += 1
                ops += 1
                if ops >= self._BATCH_LIMIT:
                    _flush()
            batch.delete(psnap.reference)
            counts["portfolios"] += 1
            ops += 1
            if ops >= self._BATCH_LIMIT:
                _flush()

        _flush()
        return counts


class InMemoryFirestoreStore:
    """Test double — dict-backed; matches `SavedScenarioStore` protocol."""

    def __init__(self) -> None:
        self.scenarios: dict[str, SavedScenarioRecord] = {}
        self.portfolios: dict[str, SavedPortfolioRecord] = {}
        self.snapshots: dict[str, dict[str, PortfolioSnapshotRecord]] = {}
        self._next_id = 0
        self._usage: dict[str, dict[str, float]] = {}
        self._throttle: dict[str, dict[str, Any]] = {}
        self._audit: list[dict[str, Any]] = []
        # A lock makes reserve/settle atomic so the concurrency guard is testable.
        self._lock = threading.Lock()

    def _new_id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}_{self._next_id}"

    # Scenarios
    def save_scenario(self, record: SavedScenarioRecord) -> str:
        sid = self._new_id("sc")
        self.scenarios[sid] = record.model_copy(update={"id": sid})
        return sid

    def get_scenario(self, scenario_id: str) -> SavedScenarioRecord | None:
        return self.scenarios.get(scenario_id)

    def list_scenarios(
        self, *, tag: str | None = None, limit: int = 50
    ) -> list[SavedScenarioListItem]:
        items = [rec for rec in self.scenarios.values() if tag is None or tag in rec.tags]
        items.sort(key=lambda r: r.created_at, reverse=True)
        return [_to_list_item(r) for r in items[:limit]]

    def delete_scenario(self, scenario_id: str) -> None:
        self.scenarios.pop(scenario_id, None)

    # Portfolios
    def save_portfolio(self, record: SavedPortfolioRecord) -> str:
        pid = self._new_id("pf")
        self.portfolios[pid] = record.model_copy(update={"id": pid})
        self.snapshots.setdefault(pid, {})
        return pid

    def get_portfolio(self, portfolio_id: str) -> SavedPortfolioRecord | None:
        return self.portfolios.get(portfolio_id)

    def list_portfolios(self) -> list[SavedPortfolioRecord]:
        return sorted(self.portfolios.values(), key=lambda r: r.created_at, reverse=True)

    # Snapshots
    def save_snapshot(self, portfolio_id: str, record: PortfolioSnapshotRecord) -> str:
        if portfolio_id not in self.portfolios:
            raise LookupError(f"Unknown portfolio {portfolio_id!r}")
        sid = self._new_id("sn")
        self.snapshots.setdefault(portfolio_id, {})[sid] = record.model_copy(
            update={"id": sid, "portfolio_id": portfolio_id}
        )
        return sid

    def get_snapshot(self, portfolio_id: str, snapshot_id: str) -> PortfolioSnapshotRecord | None:
        return self.snapshots.get(portfolio_id, {}).get(snapshot_id)

    def list_snapshots(self, portfolio_id: str) -> list[PortfolioSnapshotRecord]:
        return sorted(
            self.snapshots.get(portfolio_id, {}).values(),
            key=lambda r: r.as_of_date,
            reverse=True,
        )

    # Operational counters
    def reserve_budget(self, day: str, amount: float, *, cap: float) -> bool:
        with self._lock:
            data = self._usage.setdefault(day, {})
            spent = float(data.get("spent", 0.0))
            reserved = float(data.get("reserved", 0.0))
            if spent + reserved + amount > cap:
                return False
            data["reserved"] = reserved + amount
            return True

    def settle_budget(
        self, day: str, *, reserved: float, actual: float, tokens_in: int, tokens_out: int
    ) -> None:
        with self._lock:
            data = self._usage.setdefault(day, {})
            data["reserved"] = max(0.0, float(data.get("reserved", 0.0)) - reserved)
            data["spent"] = float(data.get("spent", 0.0)) + actual
            data["tokens_in"] = int(data.get("tokens_in", 0)) + tokens_in
            data["tokens_out"] = int(data.get("tokens_out", 0)) + tokens_out
            data["calls"] = int(data.get("calls", 0)) + 1

    def increment_daily_run(self, day: str) -> int:
        with self._lock:
            data = self._usage.setdefault(day, {})
            data["runs"] = int(data.get("runs", 0)) + 1
            return data["runs"]

    def usage_daily(self, day: str) -> dict[str, float]:
        return dict(self._usage.get(day, {}))

    def unlock_failure_count(self, key: str, *, window_seconds: int) -> int:
        data = self._throttle.get(key)
        if not data or _window_expired(data.get("window_start"), window_seconds):
            return 0
        return int(data.get("count", 0))

    def record_failed_unlock(self, key: str, *, window_seconds: int) -> int:
        with self._lock:
            data = self._throttle.get(key)
            if not data or _window_expired(data.get("window_start"), window_seconds):
                self._throttle[key] = {"count": 1, "window_start": utcnow()}
                return 1
            data["count"] = int(data.get("count", 0)) + 1
            return data["count"]

    def clear_unlock_failures(self, key: str) -> None:
        self._throttle.pop(key, None)

    # Audit + data governance
    def record_audit(
        self,
        *,
        action: str,
        target_type: str,
        target_id: str | None = None,
        request_id: str | None = None,
        ip_hash: str | None = None,
    ) -> None:
        self._audit.append(
            {
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "request_id": request_id,
                "ip_hash": ip_hash,
                "at": utcnow(),
            }
        )

    def list_audit(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return list(reversed(self._audit))[:limit]

    def export_all(self) -> dict[str, Any]:
        portfolios = []
        for pid, rec in self.portfolios.items():
            snaps = [s.model_dump(mode="json") for s in self.snapshots.get(pid, {}).values()]
            portfolios.append({**rec.model_dump(mode="json"), "snapshots": snaps})
        return {
            "scenarios": [r.model_dump(mode="json") for r in self.scenarios.values()],
            "portfolios": portfolios,
        }

    def purge_all(self) -> dict[str, int]:
        counts = {
            "scenarios": len(self.scenarios),
            "portfolios": len(self.portfolios),
            "snapshots": sum(len(s) for s in self.snapshots.values()),
        }
        self.scenarios.clear()
        self.portfolios.clear()
        self.snapshots.clear()
        return counts


def utcnow() -> datetime:
    return datetime.now(UTC)
