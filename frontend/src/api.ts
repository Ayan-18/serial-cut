export const jsonHeaders = { "Content-Type": "application/json" };

let localApiToken: string | null = null;

export async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const request = await withLocalApiToken(init);
  const response = await fetch(url, request);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail ?? `Ошибка запроса: HTTP ${response.status}`);
  return data as T;
}

async function withLocalApiToken(init?: RequestInit): Promise<RequestInit | undefined> {
  const method = (init?.method ?? "GET").toUpperCase();
  if (["GET", "HEAD", "OPTIONS"].includes(method)) return init;
  localApiToken ??= await fetchLocalApiToken();
  const headers = new Headers(init?.headers);
  headers.set("X-SerialCuts-Token", localApiToken);
  return {
    ...init,
    headers,
  };
}

async function fetchLocalApiToken(): Promise<string> {
  const response = await fetch("/api/security-token");
  const data = await response.json().catch(() => ({}));
  if (!response.ok || typeof data.token !== "string") {
    throw new Error("Не удалось получить локальный API token");
  }
  return data.token;
}
