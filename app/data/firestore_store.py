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

    def save_scenario(self, record: SavedScenarioRecord) -> str: ...
    def get_scenario(self, scenario_id: str) -> SavedScenarioRecord | None: ...
    def list_scenarios(
        self, *, tag: str | None = None, limit: int = 50
    ) -> list[SavedScenarioListItem]: ...
    def delete_scenario(self, scenario_id: str) -> None: ...

    def save_portfolio(self, record: SavedPortfolioRecord) -> str: ...
    def get_portfolio(self, portfolio_id: str) -> SavedPortfolioRecord | None: ...
    def list_portfolios(self) -> list[SavedPortfolioRecord]: ...

    def save_snapshot(self, portfolio_id: str, record: PortfolioSnapshotRecord) -> str: ...
    def get_snapshot(
        self, portfolio_id: str, snapshot_id: str
    ) -> PortfolioSnapshotRecord | None: ...
    def list_snapshots(self, portfolio_id: str) -> list[PortfolioSnapshotRecord]: ...


def _payload_size_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, default=str).encode("utf-8"))


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


class InMemoryFirestoreStore:
    """Test double — dict-backed; matches `SavedScenarioStore` protocol."""

    def __init__(self) -> None:
        self.scenarios: dict[str, SavedScenarioRecord] = {}
        self.portfolios: dict[str, SavedPortfolioRecord] = {}
        self.snapshots: dict[str, dict[str, PortfolioSnapshotRecord]] = {}
        self._next_id = 0

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


def utcnow() -> datetime:
    return datetime.now(UTC)
