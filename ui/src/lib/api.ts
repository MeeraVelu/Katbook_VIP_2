// Single fetch client. Same-origin: nginx (prod) / vite (dev) proxy /api, /health,
// /ready to the API service UNCHANGED. Injects the X-API-Key header from local
// storage and unwraps the backend error envelope into a typed ApiError.
import type {
  BatchRequest,
  BatchResponse,
  FacetsResponse,
  HealthResponse,
  JobStatus,
  Page,
  ReadyResponse,
  RegisterVideoRequest,
  RegisterVideoResponse,
  SearchMode,
  SearchResponse,
  SoftDeleteResponse,
  VideoDetail,
  VideoFilters,
  VideoSummary,
  ErrorEnvelope,
} from "./types";

const KEY_STORAGE = "katbook_api_key";

export function getApiKey(): string {
  return localStorage.getItem(KEY_STORAGE) ?? "";
}
export function setApiKey(key: string): void {
  if (key) localStorage.setItem(KEY_STORAGE, key);
  else localStorage.removeItem(KEY_STORAGE);
}

// Source-video URL for an HTML5 <video> element. A media element can't send the
// X-API-Key header, so the key rides as a query param (the /stream endpoint
// accepts either). Same-origin relative path -> nginx/vite proxy it to the API.
export function streamUrl(videoId: string): string {
  const key = getApiKey();
  return `/api/v1/videos/${videoId}/stream${key ? `?key=${encodeURIComponent(key)}` : ""}`;
}

export class ApiError extends Error {
  status: number;
  code: string;
  requestId: string | null;
  constructor(status: number, env?: ErrorEnvelope | null, fallback?: string) {
    super(env?.message ?? fallback ?? `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = env?.code ?? "error";
    this.requestId = env?.request_id ?? null;
  }
}

interface RequestOpts {
  method?: string;
  body?: unknown;
  form?: FormData;
  allowStatuses?: number[]; // treat these non-2xx as success (e.g. /ready 503)
}

async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const key = getApiKey();
  if (key) headers["X-API-Key"] = key;

  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }

  const res = await fetch(path, { method: opts.method ?? "GET", headers, body });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }

  if (!res.ok && !(opts.allowStatuses ?? []).includes(res.status)) {
    const env = (data as { error?: ErrorEnvelope } | null)?.error ?? null;
    throw new ApiError(res.status, env, text.slice(0, 200));
  }
  return data as T;
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "" && v !== null) sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  // health / readiness
  health: () => request<HealthResponse>("/health"),
  ready: () => request<ReadyResponse>("/ready", { allowStatuses: [503] }),

  // videos
  listVideos: (page: number, pageSize: number, filters: VideoFilters = {}) =>
    request<Page<VideoSummary>>(
      `/api/v1/videos${qs({ page, page_size: pageSize, ...filters })}`,
    ),
  getVideo: (id: string) => request<VideoDetail>(`/api/v1/videos/${id}`),
  facets: () => request<FacetsResponse>("/api/v1/videos/facets"),
  registerVideo: (body: RegisterVideoRequest) =>
    request<RegisterVideoResponse>("/api/v1/videos", { method: "POST", body }),
  uploadVideo: (file: File, force = false) => {
    const form = new FormData();
    form.append("file", file);
    form.append("force", String(force));
    return request<RegisterVideoResponse>("/api/v1/videos/upload", { method: "POST", form });
  },
  batch: (body: BatchRequest) =>
    request<BatchResponse>("/api/v1/videos/batch", { method: "POST", body }),
  softDelete: (id: string) =>
    request<SoftDeleteResponse>(`/api/v1/videos/${id}`, { method: "DELETE" }),

  // jobs
  getJob: (id: string) => request<JobStatus>(`/api/v1/jobs/${id}`),

  // search
  search: (q: string, mode: SearchMode, limit: number) =>
    request<SearchResponse>(`/api/v1/search${qs({ q, mode, limit })}`),
};
