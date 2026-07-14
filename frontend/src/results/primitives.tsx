export function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {sub ? <small>{sub}</small> : null}
    </div>
  );
}

/** Sortable column header with aria-sort semantics; `numeric` right-aligns to
 * match `td.num` cells. */
export function SortableTh({
  label,
  active,
  dir,
  onToggle,
  numeric = false
}: {
  label: string;
  active: boolean;
  dir: "asc" | "desc";
  onToggle: () => void;
  numeric?: boolean;
}) {
  const arrow = active ? (dir === "asc" ? "▲" : "▼") : "";
  return (
    <th
      className={`sortable${numeric ? " num" : ""}${active ? " sorted" : ""}`}
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <button type="button" onClick={onToggle}>
        {label}
        {arrow ? (
          <span className="sort-arrow" aria-hidden="true">
            {" "}
            {arrow}
          </span>
        ) : null}
      </button>
    </th>
  );
}
