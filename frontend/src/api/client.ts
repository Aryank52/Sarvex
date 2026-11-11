const API_ROOT = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  code: string;
  detail: unknown;
  correlationId: string | null;

  constructor(
    message: string,
    status: number,
    code = "request_failed",
    detail: unknown = null,
    correlationId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.correlationId = correlationId;
  }
}

export function buildQuery(
  params: Record<string, string | number | boolean | null | undefined>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function parseError(response: Response): Promise<ApiError> {
  let body: {
    code?: string;
    message?: string;
    detail?: unknown;
    correlation_id?: string | null;
  } | null = null;
  try {
    body = (await response.json()) as typeof body;
  } catch {
    body = null;
  }
  if (!body) {
    body = { message: response.statusText || `HTTP ${response.status}` };
  }
  return new ApiError(
    body.message || `Request failed with HTTP ${response.status}`,
    response.status,
    body.code || "request_failed",
    body.detail,
    body.correlation_id ?? null,
  );
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_ROOT}/api/v1${path}`, {
    ...init,
    headers,
    signal: init?.signal,
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function patch<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function layerPngUrl(resultId: string, layer: string): string {
  return `${API_ROOT}/api/v1/results/${encodeURIComponent(resultId)}/layers/${encodeURIComponent(layer)}?format=png`;
}

export function layerGeoTiffUrl(resultId: string, layer: string): string {
  return `${API_ROOT}/api/v1/results/${encodeURIComponent(resultId)}/layers/${encodeURIComponent(layer)}?format=geotiff`;
}

export function reportDownloadUrl(reportId: string): string {
  return `${API_ROOT}/api/v1/reports/${encodeURIComponent(reportId)}/download`;
}

export function apiRoot(): string {
  return API_ROOT;
}
