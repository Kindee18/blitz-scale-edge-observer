/**
 * Worker unit tests - tests routing logic by importing and calling the worker
 * fetch handler directly, without needing a live Wrangler/Cloudflare runtime.
 */

import { describe, expect, it, jest } from "@jest/globals";

// Enable fake timers globally for these tests
jest.useFakeTimers();

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
const GameTrackerDO = workerModule.GameTrackerDO;

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

describe("GameTrackerDO Durable Object", () => {
  it("initializes correctly and handles health check", async () => {
    const state = {
      id: { toString: () => "mock-game-id" },
      waitUntil: () => {},
    };
    const env = makeEnv();
    const doInstance = new GameTrackerDO(state, env);

    const req = new Request("http://do/health");
    const resp = await doInstance.fetch(req);
    expect(resp.status).toBe(200);
    const data = await resp.json();
    expect(data.status).toBe("healthy");
    expect(data.gameId).toBe("mock-game-id");
  });

  it("handles broadcast messages", async () => {
    const state = {
      id: { toString: () => "mock-game-id" },
      waitUntil: () => {},
    };
    const env = makeEnv();
    const doInstance = new GameTrackerDO(state, env);

    const update = {
      game_id: "mock-game-id",
      player_id: "P1",
      fantasy_delta: { current_points: 10.5 },
    };

    const req = new Request("http://do/broadcast", {
      method: "POST",
      body: JSON.stringify(update),
    });

    const resp = await doInstance.fetch(req);
    expect(resp.status).toBe(200);
    const result = await resp.json();
    expect(result.success).toBe(true);
    expect(result.recipients).toBe(0);
  });
});
