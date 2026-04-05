/**
 * Worker unit tests - tests routing logic by importing and calling the worker
 * fetch handler directly, without needing a live Wrangler/Cloudflare runtime.
 */

import { describe, expect, it } from "@jest/globals";

// Minimal env mock matching what worker.js expects
function makeEnv(overrides = {}) {
  return {
    GAME_STATE_KV: { get: async () => null, put: async () => {} },
    GAME_TRACKER_DO: {
      idFromName: () => ({ toString: () => "mock-id" }),
      get: () => ({
        fetch: async () => new Response("ok", { status: 200 }),
      }),
    },
    WEBHOOK_SECRET_TOKEN: "test-secret",
    REQUIRE_JWT_AUTH: "false",
    WS_ROLLOUT_PERCENT: "100",
    JWT_ISSUER: "",
    JWT_AUDIENCE: "",
    ...overrides,
  };
}

// Dynamically import the worker module
const workerModule = await import("../../edge/worker.js");
const worker = workerModule.default;

describe("Worker routing", () => {
  it("returns 200 and correct body on root health check", async () => {
    const req = new Request("https://example.com/");
    const resp = await worker.fetch(req, makeEnv(), {});
    expect(resp.status).toBe(200);
    const text = await resp.text();
    expect(text).toContain("Blitz-Scale Edge Hub Active");
  });

  it("returns 200 on /health endpoint", async () => {
    const req = new Request("https://example.com/health");
    const resp = await worker.fetch(req, makeEnv(), {});
    expect(resp.status).toBe(200);
  });

  it("returns 401 on /webhook/update without token", async () => {
    const req = new Request("https://example.com/webhook/update", {
      method: "POST",
      body: JSON.stringify({ events: [] }),
      headers: { "Content-Type": "application/json" },
    });
    const resp = await worker.fetch(req, makeEnv(), {});
    expect(resp.status).toBe(401);
  });

  it("returns 401 on /webhook/update with wrong token", async () => {
    const req = new Request("https://example.com/webhook/update", {
      method: "POST",
      body: JSON.stringify({ events: [] }),
      headers: {
        "Content-Type": "application/json",
        "X-Webhook-Token": "wrong-token",
      },
    });
    const resp = await worker.fetch(req, makeEnv(), {});
    expect(resp.status).toBe(401);
  });
});
