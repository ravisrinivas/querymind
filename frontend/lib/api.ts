export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, {
      ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) }, cache: "no-store",
    });
  } catch {
    throw new ApiError(0, `Cannot reach the QueryMind API at ${API}. Is the backend running (uvicorn app.main:app --port 8000)?`);
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch { /* keep statusText */ }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const post = <T,>(p: string, body: unknown) => api<T>(p, { method: "POST", body: JSON.stringify(body) });
export const put = <T,>(p: string, body: unknown) => api<T>(p, { method: "PUT", body: JSON.stringify(body) });
export const del = <T,>(p: string) => api<T>(p, { method: "DELETE" });
