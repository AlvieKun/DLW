import type {
  EventRequest,
  NextBestAction,
  HealthResponse,
  LearnerStateResponse,
  PortfolioResponse,
  CalibrationResponse,
  LearnersListResponse,
  AuthUser,
  RegisterRequest as RegisterReq,
  LoginRequest as LoginReq,
  UserProfile,
  ProfileUpdate,
  UserEvent,
  UserUpload,
  AgentStatusResponse,
  WeeklySummary,
} from "./types";

// ─── Config ───
const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
const IS_DEV = process.env.NODE_ENV === "development";

// We proxy through Next.js rewrites to avoid CORS issues
// /api/proxy/:path* → backend/:path*
function proxyUrl(path: string): string {
  // In browser, use the proxy; on server, call directly
  if (typeof window !== "undefined") {
    return `/api/proxy${path}`;
  }
  return `${BASE_URL}${path}`;
}

// ─── Request log (dev only) ───
interface ApiLog {
  method: string;
  url: string;
  status: number;
  durationMs: number;
  ok: boolean;
  timestamp: string;
}
const _logs: ApiLog[] = [];
export function getApiLogs(): ApiLog[] {
  return [..._logs];
}
export function clearApiLogs(): void {
  _logs.length = 0;
}

// ─── Fetch wrapper ───
async function apiFetch<T>(
  path: string,
  init?: RequestInit
): Promise<{ data: T | null; error: string | null; status: number }> {
  const url = proxyUrl(path);
  const start = Date.now();
  let status = 0;
  try {
    const res = await fetch(url, {
      ...init,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers || {}),
      },
    });
    status = res.status;
    const durationMs = Date.now() - start;

    if (IS_DEV) {
      const log: ApiLog = {
        method: init?.method || "GET",
        url,
        status,
        durationMs,
        ok: res.ok,
        timestamp: new Date().toISOString(),
      };
      _logs.push(log);
      if (_logs.length > 200) _logs.shift();
      console.log(`[API] ${log.method} ${path} → ${status} (${durationMs}ms)`);
    }

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return { data: null, error: `HTTP ${status}: ${text}`, status };
    }

    const data = (await res.json()) as T;
    return { data, error: null, status };
  } catch (err) {
    const durationMs = Date.now() - start;
    const error = err instanceof Error ? err.message : String(err);
    if (IS_DEV) {
      _logs.push({
        method: init?.method || "GET",
        url,
        status: 0,
        durationMs,
        ok: false,
        timestamp: new Date().toISOString(),
      });
    }
    return { data: null, error, status: 0 };
  }
}

// ─── Typed API functions ───

export async function getHealth() {
  return apiFetch<HealthResponse>("/health");
}

export async function postEvent(event: EventRequest) {
  return apiFetch<NextBestAction>("/api/v1/events", {
    method: "POST",
    body: JSON.stringify(event),
  });
}

export async function getLearners() {
  return apiFetch<LearnersListResponse>("/api/v1/learners");
}

// ─── "Me" convenience endpoints (no learnerId needed) ───

export async function getMyState() {
  return apiFetch<LearnerStateResponse>("/api/v1/me/state");
}

export async function getMyPortfolio(entryType?: string, limit?: number) {
  const params = new URLSearchParams();
  if (entryType) params.set("entry_type", entryType);
  if (limit !== undefined) params.set("limit", String(limit));
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<PortfolioResponse>(`/api/v1/me/portfolio${qs}`);
}

// ─── Legacy per-learner endpoints (auth-scoped, kept for compat) ───

export async function getLearnerState(learnerId: string) {
  return apiFetch<LearnerStateResponse>(
    `/api/v1/learners/${encodeURIComponent(learnerId)}/state`
  );
}

export async function deleteLearnerState(learnerId: string) {
  return apiFetch<{ learner_id: string; deleted: boolean }>(
    `/api/v1/learners/${encodeURIComponent(learnerId)}/state`,
    { method: "DELETE" }
  );
}

export async function getPortfolio(
  learnerId: string,
  entryType?: string,
  limit?: number
) {
  const params = new URLSearchParams();
  if (entryType) params.set("entry_type", entryType);
  if (limit !== undefined) params.set("limit", String(limit));
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<PortfolioResponse>(
    `/api/v1/learners/${encodeURIComponent(learnerId)}/portfolio${qs}`
  );
}

export async function getCalibration() {
  return apiFetch<CalibrationResponse>("/api/v1/calibration");
}

// ─── Auth API ───

export async function register(data: RegisterReq) {
  return apiFetch<AuthUser>("/auth/register", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function login(data: LoginReq) {
  return apiFetch<AuthUser>("/auth/login", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function logout() {
  return apiFetch<{ ok: boolean }>("/auth/logout", { method: "POST" });
}

export async function getMe() {
  return apiFetch<AuthUser>("/auth/me");
}

// ─── Profile API ───

export async function getProfile() {
  return apiFetch<UserProfile>("/profile");
}

export async function updateProfile(data: ProfileUpdate) {
  return apiFetch<UserProfile>("/profile", {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function completeOnboarding(data: ProfileUpdate) {
  return apiFetch<UserProfile>("/profile/onboarding/complete", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// ─── User Events API ───

export async function createUserEvent(data: {
  concept: string;
  score?: number | null;
  time_spent_minutes?: number | null;
  event_type?: string;
  notes?: string;
  source?: string;
}) {
  return apiFetch<UserEvent>("/events", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function getUserEvents(limit = 100) {
  return apiFetch<{ events: UserEvent[]; count: number }>(
    `/events?limit=${limit}`
  );
}

// ─── Uploads API ───

export async function uploadFile(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const url = proxyUrl("/uploads");
  const start = Date.now();
  try {
    const res = await fetch(url, {
      method: "POST",
      credentials: "include",
      body: formData,
    });
    const durationMs = Date.now() - start;
    if (IS_DEV) {
      _logs.push({
        method: "POST",
        url,
        status: res.status,
        durationMs,
        ok: res.ok,
        timestamp: new Date().toISOString(),
      });
    }
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return { data: null, error: `HTTP ${res.status}: ${text}`, status: res.status };
    }
    const data = (await res.json()) as UserUpload;
    return { data, error: null, status: res.status };
  } catch (err) {
    const error = err instanceof Error ? err.message : String(err);
    return { data: null, error, status: 0 };
  }
}

export async function getUserUploads() {
  return apiFetch<{ uploads: UserUpload[]; count: number }>("/uploads");
}

// ─── System / Diagnostics API ───

export async function getAgentsStatus() {
  return apiFetch<AgentStatusResponse>("/api/v1/system/agents/status");
}

// ─── Weekly Summary API ───

export async function getWeeklySummary() {
  return apiFetch<WeeklySummary>("/api/v1/summary/weekly");
}

export async function regenerateWeeklySummary() {
  return apiFetch<WeeklySummary>("/api/v1/summary/weekly/generate", {
    method: "POST",
  });
}
