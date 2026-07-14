import { slugify } from "./format";

export type CsvCell = string | number | null | undefined;
export interface CsvBundleFile {
  filename: string;
  headers: string[];
  rows: CsvCell[][];
}

// Excel formula-injection guard (OWASP): TEXT cells starting with one of these
// get a leading apostrophe so spreadsheet apps treat them as literals. Exports
// carry LLM/user-influenced text (factor reasoning, analog rationale), so this
// is load-bearing, not cosmetic. Number-typed cells stay raw — negative
// decimals like -0.0612 must remain machine-parseable, which is why the guard
// keys on the cell's JS type, not its first character alone.
const FORMULA_PREFIXES = ["=", "+", "-", "@", "\t", "\r"];

export function csvEscape(field: string): string {
  if (/[",\r\n]/.test(field)) {
    return `"${field.replace(/"/g, '""')}"`;
  }
  return field;
}

function guardTextCell(value: string): string {
  return FORMULA_PREFIXES.some((prefix) => value.startsWith(prefix)) ? `'${value}` : value;
}

export function toCsv(headers: string[], rows: CsvCell[][]): string {
  const renderCell = (cell: CsvCell): string => {
    if (cell == null) return "";
    if (typeof cell === "number") return String(cell);
    return csvEscape(guardTextCell(cell));
  };
  const lines = [headers.map((header) => csvEscape(header)).join(",")];
  for (const row of rows) {
    lines.push(row.map(renderCell).join(","));
  }
  return lines.join("\r\n");
}

export function csvFilename(
  portfolio: string,
  scenario: string,
  date: string,
  table: string
): string {
  return `nami_${slugify(portfolio)}_${slugify(scenario)}_${date}_${table}.csv`;
}

export function downloadCsv(filename: string, headers: string[], rows: CsvCell[][]): void {
  // UTF-8 BOM (U+FEFF) so Excel detects the encoding (narratives/reasoning can
  // carry non-ASCII). Built via fromCharCode so no invisible char sits in source.
  const bom = String.fromCharCode(0xfeff);
  const blob = new Blob([bom + toCsv(headers, rows)], {
    type: "text/csv;charset=utf-8"
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export async function downloadCsvZip(filename: string, files: CsvBundleFile[]): Promise<void> {
  const { strToU8, zipSync } = await import("fflate");
  const bom = String.fromCharCode(0xfeff);
  const entries = Object.fromEntries(
    files.map((file) => [file.filename, strToU8(bom + toCsv(file.headers, file.rows))])
  );
  const zipped = zipSync(entries, { level: 6 });
  const bytes = zipped.buffer.slice(
    zipped.byteOffset,
    zipped.byteOffset + zipped.byteLength
  ) as ArrayBuffer;
  const blob = new Blob([bytes], { type: "application/zip" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
