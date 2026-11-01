export class ApiError extends Error {
  code: string;
  remediation: string;
  status: number;

  constructor(status: number, body: { error?: { code?: string; message?: string; remediation?: string } }) {
    super(body.error?.message || `Request failed (${status})`);
    this.status = status;
    this.code = body.error?.code || "request_failed";
    this.remediation = body.error?.remediation || "";
  }
}

const base = () => process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function api<T>(path: string, token: string | null, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${base()}${path}`, { ...init, headers });
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const body = text ? JSON.parse(text) : {};
  if (!response.ok) throw new ApiError(response.status, body);
  return body as T;
}

export async function apiBlob(path: string, token: string): Promise<Blob> {
  const response = await fetch(`${base()}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) {
    const text = await response.text();
    let body = {};
    try {
      body = JSON.parse(text);
    } catch {
      body = {};
    }
    throw new ApiError(response.status, body);
  }
  return response.blob();
}
