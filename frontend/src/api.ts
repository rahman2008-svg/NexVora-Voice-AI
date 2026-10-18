// All network access lives here. The browser never loads the model; it only calls the backend.
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
export const GENERATION_TIMEOUT_MS = 5 * 60 * 1000;

export type Mode = "auto" | "design" | "clone";
export type DesignKey = "gender" | "age" | "pitch" | "style" | "accent";
export type DesignValues = Record<DesignKey, string>;
export type ModelState = "ready" | "loading" | "unavailable" | "not_loaded";

export interface HealthResponse {
  status: ModelState;
  service: string;
  version: string;
  model: { id: string; state: ModelState; device: string | null; detail: string | null };
  limits: { max_text_chars: number; min_speed: number; max_speed: number; max_upload_mb: number };
  capabilities: { voice_cloning: boolean };
  design_options: Record<DesignKey, string[]>;
}

export interface GenerateResult {
  blob: Blob;
  durationSeconds: number | null;
}

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status = 0) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    const e = body?.error;
    if (e && typeof e.code === "string") return new ApiError(e.code, String(e.message ?? ""), res.status);
  } catch {
    /* not JSON */
  }
  return new ApiError(res.status >= 500 ? "internal_error" : "unknown", "", res.status);
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/api/health`, { signal });
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as HealthResponse;
}

async function post(path: string, init: RequestInit, outer: AbortSignal): Promise<GenerateResult> {
  const controller = new AbortController();
  let timedOut = false;
  const onAbort = () => controller.abort();
  outer.addEventListener("abort", onAbort);
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, GENERATION_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE}${path}`, { ...init, signal: controller.signal });
    if (!res.ok) throw await toApiError(res);
    const blob = await res.blob();
    const d = Number(res.headers.get("X-Audio-Duration"));
    return { blob, durationSeconds: Number.isFinite(d) && d > 0 ? d : null };
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (timedOut) throw new ApiError("timeout", "");
    if (outer.aborted) throw new ApiError("aborted", "");
    throw new ApiError("network", "");
  } finally {
    window.clearTimeout(timer);
    outer.removeEventListener("abort", onAbort);
  }
}

export interface CommonParams {
  text: string;
  speed: number;
  numStep: number;
}

export function generateSpeech(
  p: CommonParams & { mode: "auto" | "design"; design: DesignValues },
  signal: AbortSignal,
): Promise<GenerateResult> {
  const body = JSON.stringify({
    text: p.text,
    mode: p.mode,
    design: p.mode === "design" ? p.design : null,
    speed: p.speed,
    num_step: p.numStep,
  });
  return post("/api/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body }, signal);
}

export function generateClone(
  p: CommonParams & { refAudio: File; refText: string; consent: boolean },
  signal: AbortSignal,
): Promise<GenerateResult> {
  const form = new FormData();
  form.append("text", p.text);
  form.append("speed", String(p.speed));
  form.append("num_step", String(p.numStep));
  form.append("consent", p.consent ? "true" : "false");
  if (p.refText.trim()) form.append("ref_text", p.refText.trim());
  form.append("ref_audio", p.refAudio);
  return post("/api/generate-clone", { method: "POST", body: form }, signal);
}
