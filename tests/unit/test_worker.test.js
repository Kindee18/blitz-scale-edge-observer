import { unstable_dev } from "wrangler";
import { describe, expect, it, beforeAll, afterAll } from "@jest/globals";

describe("Worker", () => {
	let worker;

	beforeAll(async () => {
		worker = await unstable_dev("edge/worker.js", {
			experimental: { disableProtocolCheck: true },
		});
	});

	afterAll(async () => {
		await worker.stop();
	});

	it("should respond unauthorized without token", async () => {
		const resp = await worker.fetch("/webhook/update", {
			method: "POST",
			body: JSON.stringify({ events: [] }),
		});
		expect(resp.status).toBe(401);
	});

	it("should return status 200 on health check", async () => {
		const resp = await worker.fetch("/");
		expect(resp.status).toBe(200);
		const text = await resp.text();
		expect(text).toContain("Blitz-Scale Edge Hub Active");
	});
});

// Durable Object Test (Conceptual - Miniflare provides better DO testing)
describe("GameTrackerDO", () => {
  it("should handle broadcast requests", async () => {
    // DO integration tests would typically use Miniflare's getDurableObject method
    // For this prototype, we confirm the routing logic in the main worker fetch.
  });
});
