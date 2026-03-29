import http from 'k6/http';
import { check, sleep, group } from 'k6';
import ws from 'k6/ws';
import { Trend, Rate, Counter, Gauge } from 'k6/metrics';

/**
 * 100x Traffic Spike Test for FantasyPros Game Day
 * 
 * Simulates extreme traffic surge during NFL Sunday 1PM ET kickoffs
 * - Normal baseline: ~100 concurrent users per game
 * - 100x spike: 10,000 concurrent users per game
 * - Tests predictive scaling effectiveness
 * - Validates sub-100ms latency claims
 */

// Configuration
const BASE_URL = __ENV.BASE_URL || 'https://api.blitz-obs.com';
const WS_URL = __ENV.WS_URL || 'wss://api.blitz-obs.com/realtime';
const GAME_ID = __ENV.GAME_ID || 'NFL_KC_SF';

// Custom metrics for detailed analysis
const fantasyUpdateLatency = new Trend('fantasy_update_latency_ms');
const broadcastSuccessRate = new Rate('broadcast_success_rate');
const fantasyUpdatesReceived = new Counter('fantasy_updates_received');
const activeConnections = new Gauge('active_websocket_connections');
const scalingResponseTime = new Trend('scaling_response_time_ms');
const p99Latency = new Trend('p99_fantasy_latency');

// Load test configuration - 100x spike scenario
export const options = {
  scenarios: {
    // Scenario 1: 100x Spike Test (Main validation)
    spike_test: {
      executor: 'ramping-vus',
      startVUs: 100,
      stages: [
        // Baseline - normal game traffic
        { duration: '2m', target: 100 },
        
        // 50x spike - 5,000 users (touchdown drive)
        { duration: '30s', target: 5000 },
        { duration: '3m', target: 5000 },
        
        // 100x spike - 10,000 users (peak simultaneous)
        { duration: '30s', target: 10000 },
        { duration: '5m', target: 10000 },
        
        // Gradual cool down
        { duration: '2m', target: 5000 },
        { duration: '2m', target: 1000 },
        { duration: '2m', target: 100 },
      ],
      gracefulRampDown: '30s',
    },
    
    // Scenario 2: Webhook Ingestion Load
    webhook_load: {
      executor: 'constant-arrival-rate',
      rate: 100, // 100 batches per second
      timeUnit: '1s',
      duration: '15m',
      preAllocatedVUs: 50,
      maxVUs: 200,
      exec: 'webhookIngestion',
    },
  },
  
  thresholds: {
    // Sub-100ms p99 latency validation (key FantasyPros claim)
    'fantasy_update_latency_ms': ['p(99)<100'],
    'http_req_duration': ['p(99)<200'],
    'ws_connect_duration': ['p(95)<500'],
    'broadcast_success_rate': ['rate>0.99'],
    'http_req_failed': ['rate<0.01'],
  },
};

// NFL Player data for realistic testing
const NFL_PLAYERS = [
  { id: 'MAHOMES_15', name: 'Patrick Mahomes', pos: 'QB' },
  { id: 'BURROW_9', name: 'Joe Burrow', pos: 'QB' },
  { id: 'ALLEN_17', name: 'Josh Allen', pos: 'QB' },
  { id: 'HURTS_1', name: 'Jalen Hurts', pos: 'QB' },
  { id: 'MCCAFFREY_23', name: 'Christian McCaffrey', pos: 'RB' },
  { id: 'TAYLOR_28', name: 'Jonathan Taylor', pos: 'RB' },
  { id: 'HILL_10', name: 'Tyreek Hill', pos: 'WR' },
  { id: 'LAMB_88', name: 'CeeDee Lamb', pos: 'WR' },
  { id: 'KELCE_87', name: 'Travis Kelce', pos: 'TE' },
  { id: 'ANDREWS_89', name: 'Mark Andrews', pos: 'TE' },
];

// Fantasy league configurations
const SCORING_FORMATS = ['ppr', 'half_ppr', 'standard'];
const LEAGUE_COUNT = 100; // Simulate 100 different leagues

// Main test function - simulates FantasyPros mobile client
export default function () {
  const clientId = `user_${__VU}`;
  const leagueId = `league_${__VU % LEAGUE_COUNT}`;
  const scoringFormat = SCORING_FORMATS[__VU % SCORING_FORMATS.length];
  
  group('WebSocket Connection - 100x Spike', () => {
    const url = `${WS_URL}?game_id=${GAME_ID}&client_id=${clientId}&league_id=${leagueId}&scoring_format=${scoringFormat}`;
    
    const connectStart = Date.now();
    
    const res = ws.connect(url, null, function (socket) {
      let messageCount = 0;
      let lastMessageTime = Date.now();
      
      socket.on('open', () => {
        activeConnections.add(1);
        
        // Subscribe to game updates with FantasyPros context
        socket.send(JSON.stringify({
          action: 'subscribe',
          games: [GAME_ID],
          league_id: leagueId,
          scoring_format: scoringFormat,
          client_type: 'fantasypros_mobile',
          roster: generateMockRoster(),
        }));
        
        // Send periodic heartbeat
        const heartbeat = setInterval(() => {
          if (socket.readyState === 1) {
            socket.send(JSON.stringify({ type: 'ping', timestamp: Date.now() }));
          }
        }, 30000);
        
        // Close connection after duration (varies by VU for realistic spread)
        const duration = 60 + Math.random() * 120; // 1-3 minutes
        setTimeout(() => {
          clearInterval(heartbeat);
          socket.close();
        }, duration * 1000);
      });
      
      socket.on('message', (msg) => {
        const receiveTime = Date.now();
        const data = JSON.parse(msg);
        
        if (data.type === 'delta' && data.data) {
          // Track fantasy update latency
          const latency = receiveTime - data.timestamp;
          fantasyUpdateLatency.add(latency);
          fantasyUpdatesReceived.add(1);
          
          // Track p99 specifically
          p99Latency.add(latency);
          
          // Validate delta structure
          check(data, {
            'delta has player_id': (d) => d.data.player_id !== undefined,
            'delta has fantasy_delta': (d) => d.data.fantasy_delta !== undefined,
            'delta has scoring format': (d) => d.data.fantasy_delta[scoringFormat] !== undefined,
            'latency under 100ms': (d) => latency < 100,
          });
          
          messageCount++;
          lastMessageTime = receiveTime;
        }
        
        if (data.type === 'initial_state') {
          check(data, {
            'initial state received': (d) => d.data !== undefined,
          });
        }
      });
      
      socket.on('close', () => {
        activeConnections.add(-1);
        broadcastSuccessRate.add(messageCount > 0);
      });
      
      socket.on('error', (e) => {
        console.error(`WebSocket error for ${clientId}:`, e);
      });
    });
    
    const connectDuration = Date.now() - connectStart;
    scalingResponseTime.add(connectDuration);
    
    check(res, {
      'WebSocket connection established': (r) => r && r.status === 101,
      'Connection time under 500ms': (r) => connectDuration < 500,
    });
  });
  
  // Simulate user behavior: occasional health checks
  if (__VU % 10 === 0) {
    group('REST API Health', () => {
      const res = http.get(`${BASE_URL}/health`);
      
      check(res, {
        'health check status is 200': (r) => r.status === 200,
        'health check fast': (r) => r.timings.duration < 50,
      });
    });
  }
  
  // Random sleep to simulate realistic connection patterns
  sleep(Math.random() * 5 + 1);
}

// Webhook batch ingestion simulation
export function webhookIngestion() {
  const player = NFL_PLAYERS[Math.floor(Math.random() * NFL_PLAYERS.length)];
  
  // Simulate realistic game events
  const events = Array(5).fill(null).map((_, i) => ({
    game_id: GAME_ID,
    player_id: player.id,
    player_name: player.name,
    timestamp: Date.now(),
    stat_delta: generateStatDelta(player.pos),
    fantasy_delta: generateFantasyDelta(player.pos),
    scoring_format: SCORING_FORMATS[i % SCORING_FORMATS.length],
    projected_points: generateProjectedPoints(player.pos),
  }));
  
  const payload = { events };
  
  const startTime = Date.now();
  
  const res = http.post(`${BASE_URL}/webhook/update`, JSON.stringify(payload), {
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${__ENV.WEBHOOK_SECRET || 'test-secret'}`,
    },
  });
  
  const processingTime = Date.now() - startTime;
  scalingResponseTime.add(processingTime);
  
  check(res, {
    'webhook returns 200': (r) => r.status === 200,
    'webhook processing under 200ms': (r) => processingTime < 200,
    'webhook response has success': (r) => {
      const body = JSON.parse(r.body);
      return body.success === true;
    },
    'all events processed': (r) => {
      const body = JSON.parse(r.body);
      return body.results && body.results.processed === 5;
    },
  });
}

// Helper functions
function generateMockRoster() {
  const positions = ['QB', 'RB', 'RB', 'WR', 'WR', 'WR', 'TE', 'FLEX', 'K', 'DEF'];
  return positions.map((pos, i) => ({
    position: pos,
    player_id: NFL_PLAYERS[(i + __VU) % NFL_PLAYERS.length].id,
    player_name: NFL_PLAYERS[(i + __VU) % NFL_PLAYERS.length].name,
  }));
}

function generateStatDelta(position) {
  const deltas = {
    'QB': {
      passing_yards: Math.floor(Math.random() * 30) + 5,
      passing_tds: Math.random() > 0.9 ? 1 : 0,
      passing_ints: Math.random() > 0.95 ? 1 : 0,
    },
    'RB': {
      rushing_yards: Math.floor(Math.random() * 20) + 2,
      rushing_tds: Math.random() > 0.95 ? 1 : 0,
      receptions: Math.random() > 0.7 ? 1 : 0,
    },
    'WR': {
      receiving_yards: Math.floor(Math.random() * 25) + 3,
      receptions: Math.random() > 0.6 ? 1 : 0,
      receiving_tds: Math.random() > 0.92 ? 1 : 0,
    },
    'TE': {
      receiving_yards: Math.floor(Math.random() * 20) + 2,
      receptions: Math.random() > 0.65 ? 1 : 0,
      receiving_tds: Math.random() > 0.94 ? 1 : 0,
    },
  };
  return deltas[position] || deltas['WR'];
}

function generateFantasyDelta(position) {
  const basePoints = {
    'QB': { ppr: 4.5, half_ppr: 4.5, standard: 4.5 },
    'RB': { ppr: 3.0, half_ppr: 2.5, standard: 2.0 },
    'WR': { ppr: 3.5, half_ppr: 3.0, standard: 2.5 },
    'TE': { ppr: 3.0, half_ppr: 2.5, standard: 2.0 },
  };
  return basePoints[position] || basePoints['WR'];
}

function generateProjectedPoints(position) {
  const projections = {
    'QB': 18.5,
    'RB': 14.2,
    'WR': 12.8,
    'TE': 9.5,
  };
  return projections[position] || 10.0;
}

// Test lifecycle hooks
export function setup() {
  console.log('Starting 100x Spike Test for FantasyPros');
  console.log(`Target: ${BASE_URL}`);
  console.log(`WebSocket: ${WS_URL}`);
  console.log(`Game: ${GAME_ID}`);
  
  // Initial health check
  const res = http.get(`${BASE_URL}/health`);
  if (res.status !== 200) {
    console.error('Health check failed! Aborting test.');
    return { abort: true };
  }
  
  return {
    startTime: Date.now(),
    targetUsers: 10000,
    baselineUsers: 100,
  };
}

export function teardown(data) {
  const duration = (Date.now() - data.startTime) / 1000;
  console.log('');
  console.log('=== 100x Spike Test Complete ===');
  console.log(`Duration: ${duration}s`);
  console.log(`Peak users: ${data.targetUsers}`);
  console.log(`Baseline: ${data.baselineUsers}`);
  console.log('==================================');
}
