export function formatNumber(
  value: number | null | undefined,
  digits = 2,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs !== 0 && (abs >= 1_000_000 || abs < 0.001)) {
    return value.toExponential(2);
  }
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  }).format(value);
}

export function formatArea(areaM2: number | null | undefined): string {
  if (areaM2 === null || areaM2 === undefined) return "—";
  if (areaM2 >= 1_000_000) return `${formatNumber(areaM2 / 1_000_000, 2)} km²`;
  if (areaM2 >= 10_000) return `${formatNumber(areaM2 / 10_000, 2)} ha`;
  return `${formatNumber(areaM2, 0)} m²`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes >= 1_073_741_824) return `${formatNumber(bytes / 1_073_741_824, 2)} GB`;
  if (bytes >= 1_048_576) return `${formatNumber(bytes / 1_048_576, 1)} MB`;
  if (bytes >= 1024) return `${formatNumber(bytes / 1024, 1)} KB`;
  return `${bytes} B`;
}

export function formatDate(value: string | null | undefined, withTime = false): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    ...(withTime ? { hour: "2-digit", minute: "2-digit", timeZoneName: "short" } : {}),
  }).format(date);
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return `${formatNumber(value * 100, digits)}%`;
}

export function titleCase(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function sentenceCase(value: string): string {
  return value.replaceAll("_", " ").toLowerCase();
}

export function shortId(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length > 14 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

export function stageClass(stage: string | null | undefined): string {
  const key = (stage || "").toUpperCase();
  if (key === "CONFIRMED") return "stage stage-confirmed";
  if (key === "HYPOTHESIZED") return "stage stage-hypothesized";
  if (key === "CLASSIFIED") return "stage stage-classified";
  if (key === "DETECTED") return "stage stage-detected";
  return "stage stage-observed";
}

export function statusClass(status: string | null | undefined): string {
  const key = (status || "").toUpperCase();
  switch (key) {
    case "COMPLETED":
    case "OK":
    case "CORROBORATED":
      return "status status-good";
    case "FAILED":
    case "REJECTED":
    case "ERROR":
      return "status status-bad";
    case "PROCESSING":
    case "ANALYZING":
    case "PREPROCESSING":
    case "QUEUED":
    case "CLAIMED":
      return "status status-live";
    case "UNDER_REVIEW":
      return "status status-warn";
    default:
      return "status status-neutral";
  }
}

export function valueWithUnit(
  value: number | null | undefined,
  unit: string | null | undefined,
  digits = 2,
): string {
  if (value === null || value === undefined) return "—";
  return `${formatNumber(value, digits)}${unit ? ` ${unit}` : ""}`;
}

export function toNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return null;
}
