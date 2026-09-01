import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

describe("api", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns JSON on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 })));
    await expect(api<{ ok: boolean }>("/api/test")).resolves.toEqual({ ok: true });
  });

  it("preserves a backend error detail", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Неверные границы" }), { status: 422 })));
    await expect(api("/api/test")).rejects.toThrow("Неверные границы");
  });

  it("handles an empty error response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 500 })));
    await expect(api("/api/test")).rejects.toThrow("HTTP 500");
  });

  it("adds the local API token to unsafe requests", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: "local-token" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetch);

    await expect(api<{ ok: boolean }>("/api/test", { method: "POST" })).resolves.toEqual({ ok: true });

    const request = fetch.mock.calls[1][1] as RequestInit;
    expect(new Headers(request.headers).get("X-SerialCuts-Token")).toBe("local-token");
  });
});
