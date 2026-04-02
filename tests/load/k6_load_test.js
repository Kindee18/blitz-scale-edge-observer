import http from "k6/http";
import { check, sleep, group } from "k6";
import ws from "k6/ws";

// Configuration
const BASE_URL =
	__ENV.BASE_URL || "https://blitz-edge-observer.kindsonegbule15.workers.dev";
const WS_URL =
	__ENV.WS_URL ||
	"wss://blitz-edge-observer.kindsonegbule15.workers.dev/realtime";
const GAME_ID = __ENV.GAME_ID || "NFL_101";

// Load test stages - simulating NFL Sunday traffic patterns
export const options = {
	stages: [
		{ duration: "2m", target: 100 }, // Ramp up - Pre-game warm-up
		{ duration: "5m", target: 1000 }, // Spike - Kickoff surge
		{ duration: "10m", target: 2500 }, // Sustained - Peak game time
		{ duration: "5m", target: 5000 }, // Stress test - 5K concurrent users
		{ duration: "5m", target: 2500 }, // Cool down
		{ duration: "3m", target: 100 }, // Return to normal
	],
	thresholds: {
		http_req_duration: ["p(99)<200"], // 99% of requests under 200ms
		ws_connect_duration: ["p(95)<500"], // WebSocket connect under 500ms
		http_req_failed: ["rate<0.01"], // Less than 1% errors
	},
};

// Simulates a FantasyPros mobile client
export default function () {
	group("WebSocket Connection", () => {
		const url = `${WS_URL}?game_id=${GAME_ID}&client_id=load_test_${__VU}`;

		const res = ws.connect(url, null, function (socket) {
			socket.on("open", () => {
				// Subscribe to game updates
				socket.send(
					JSON.stringify({
						action: "subscribe",
						games: [GAME_ID],
						league_id: `league_${__VU % 10}`, // 10 different leagues
					}),
				);
			});

			socket.on("message", (msg) => {
				const data = JSON.parse(msg);
				check(data, {
					"message has type": (obj) => obj.type !== undefined,
					"message has timestamp": (obj) => obj.timestamp !== undefined,
				});
			});

			socket.on("close", () => {
				// Connection closed
			});

			// Keep connection open for 30 seconds
			sleep(30);
			socket.close();
		});

		check(res, {
			"WebSocket connection established": (r) => r && r.status === 101,
		});
	});

	group("REST API Health", () => {
		const res = http.get(`${BASE_URL}/health`);

		check(res, {
			"health check status is 200": (r) => r.status === 200,
			"health check response valid": (r) => {
				const body = JSON.parse(r.body);
				return body.status === "healthy";
			},
		});
	});

	sleep(1);
}

// Simulate batch webhook ingestion (AWS Lambda → Edge)
export function webhookIngestion() {
	group("Webhook Batch Ingestion", () => {
		const payload = {
			events: Array(10)
				.fill(null)
				.map((_, i) => ({
					game_id: GAME_ID,
					player_id: `PLAYER_${i}`,
					player_name: `Test Player ${i}`,
					timestamp: Date.now(),
					stat_delta: {
						passing_yards: Math.floor(Math.random() * 50),
						passing_tds: Math.random() > 0.8 ? 1 : 0,
					},
					fantasy_delta: {
						ppr: {
							previous_points: 10.0,
							current_points: 14.5,
							points_delta: 4.5,
						},
					},
				})),
		};

		const res = http.post(
			`${BASE_URL}/webhook/update`,
			JSON.stringify(payload),
			{
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${__ENV.WEBHOOK_SECRET || "test-secret"}`,
				},
			},
		);

		check(res, {
			"webhook returns 200": (r) => r.status === 200,
			"webhook response has success": (r) => {
				const body = JSON.parse(r.body);
				return body.success === true;
			},
			"webhook processes all events": (r) => {
				const body = JSON.parse(r.body);
				return body.results && body.results.processed === 10;
			},
		});
	});
}

// Custom metrics for tracking fantasy-specific performance
import { Trend, Rate, Counter } from "k6/metrics";

const latencyTrend = new Trend("fantasy_update_latency");
const broadcastSuccessRate = new Rate("broadcast_success_rate");
const fantasyUpdatesCounter = new Counter("fantasy_updates_received");
