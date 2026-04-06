import http from "k6/http";
import { check, sleep } from "k6";
import ws from "k6/ws";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8787";
const WS_URL = __ENV.WS_URL || "ws://localhost:8787/realtime";
const GAME_ID = __ENV.GAME_ID || "NFL_101";

export const options = {
	stages: [
		{ duration: "30s", target: 50 },
		{ duration: "60s", target: 200 },
		{ duration: "30s", target: 50 },
	],
	thresholds: {
		http_req_duration: ["p(99)<200"],
		http_req_failed: ["rate<0.01"],
	},
};

export default function () {
	// HTTP health check
	const res = http.get(`${BASE_URL}/health`);
	check(res, {
		"health status 200": (r) => r.status === 200,
		"latency < 100ms": (r) => r.timings.duration < 100,
	});

	// WebSocket connection
	const wsRes = ws.connect(
		`${WS_URL}?game_id=${GAME_ID}&client_id=local_test_${__VU}`,
		null,
		function (socket) {
			socket.on("open", () => {
				socket.send(JSON.stringify({ action: "subscribe", games: [GAME_ID] }));
			});
			socket.on("message", () => {});
			socket.setTimeout(() => socket.close(), 3000);
		}
	);
	check(wsRes, { "ws connected": (r) => r && r.status === 101 });

	sleep(1);
}
