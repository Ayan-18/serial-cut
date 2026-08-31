export const jsonHeaders = { "Content-Type": "application/json" };

export async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail ?? `Ошибка запроса: HTTP ${response.status}`);
  return data as T;
}
