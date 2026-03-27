import http from 'k6/http';
import ws from 'k6/ws';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 100 },  // Ramp up to 100 users
    { duration: '1m', target: 1000 },  // Spike to 1000 users (The Sunday Morning Rush)
    { duration: '30s', target: 0 },    // Ramp down
  ],
};

const EDGE_URL = 'http://localhost:8787'; // Dev worker address

export default function () {
  // 1. WebSocket Connection Simulation
  const url = `${EDGE_URL.replace('http', 'ws')}/realtime?game_id=NFL_101`;
  
  const res = ws.connect(url, {}, function (socket) {
    socket.on('open', () => {
      console.log('connected');
      socket.close();
    });
    
    socket.on('message', (data) => {
      const message = JSON.parse(data);
      check(message, { 'is delta': (m) => m.delta !== undefined });
    });

    socket.on('close', () => console.log('disconnected'));
    socket.on('error', (e) => console.log('error', e.error()));
  });

  check(res, { 'status is 101': (r) => r && r.status === 101 });

  // 2. HTTP Webhook Ingest Simulation
  const payload = JSON.stringify({
    events: [{
      game_id: "NFL_101",
      player_id: "P1",
      delta: { score: 7 }
    }]
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer secure-edge-token-12345',
    },
  };

  const webhook_res = http.post(`${EDGE_URL}/webhook/update`, payload, params);
  check(webhook_res, { 'webhook status 200': (r) => r.status === 200 });

  sleep(1);
}
