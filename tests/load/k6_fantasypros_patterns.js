import http from 'k6/http';
import { check, sleep, group } from 'k6';
import ws from 'k6/ws';
import { Trend, Rate, Counter } from 'k6/metrics';

/**
 * FantasyPros-Specific Load Test Patterns
 * 
 * Simulates realistic FantasyPros user behaviors:
 * - Multiple league subscriptions (users in 1-5 leagues)
 * - Concurrent roster updates across leagues
 * - Realistic player counts (10 starters + 7 bench per league)
 * - Game-day traffic patterns (1PM ET kickoff surge)
 * - My Matchups page behavior
 */

const BASE_URL = __ENV.BASE_URL || 'https://blitz-edge-observer.kindsonegbule15.workers.dev';
const WS_URL = __ENV.WS_URL || 'wss://blitz-edge-observer.kindsonegbule15.workers.dev/realtime';

// Custom metrics
const matchupUpdateLatency = new Trend('matchup_update_latency');
const rosterSyncLatency = new Trend('roster_sync_latency');
const multiLeagueUpdateRate = new Rate('multi_league_updates_success');
const startSitSignalLatency = new Trend('start_sit_signal_latency');

// FantasyPros user behavior simulation
export const options = {
  scenarios: {
    // Casual users: 1-2 leagues, check occasionally
    casual_users: {
      executor: 'ramping-vus',
      startVUs: 50,
      stages: [
        { duration: '3m', target: 2000 },
        { duration: '10m', target: 2000 },
        { duration: '3m', target: 500 },
      ],
      exec: 'casualUserBehavior',
    },
    
    // Power users: 5+ leagues, constant monitoring
    power_users: {
      executor: 'ramping-vus',
      startVUs: 10,
      stages: [
        { duration: '3m', target: 500 },
        { duration: '10m', target: 500 },
        { duration: '3m', target: 100 },
      ],
      exec: 'powerUserBehavior',
    },
    
    // My Matchups page viewers (high value users)
    matchups_viewers: {
      executor: 'constant-vus',
      vus: 1000,
      duration: '15m',
      exec: 'matchupsPageBehavior',
    },
    
    // Roster update storm (waivers, trades, lineup changes)
    roster_updates: {
      executor: 'ramping-arrival-rate',
      startRate: 10,
      timeUnit: '1s',
      preAllocatedVUs: 50,
      maxVUs: 200,
      stages: [
        { duration: '2m', target: 10 },
        { duration: '3m', target: 200 }, // Waiver wire rush
        { duration: '8m', target: 50 },
        { duration: '2m', target: 10 },
      ],
      exec: 'rosterUpdateStorm',
    },
  },
  
  thresholds: {
    'matchup_update_latency': ['p(95)<150'],
    'roster_sync_latency': ['p(95)<200'],
    'start_sit_signal_latency': ['p(99)<100'],
    'multi_league_updates_success': ['rate>0.98'],
    'http_req_failed': ['rate<0.02'],
  },
};

// NFL Week 1 Sunday 1PM games (simulated)
const ACTIVE_GAMES = [
  'NFL_KC_SF',      // Chiefs vs 49ers
  'NFL_BUF_MIA',    // Bills vs Dolphins
  'NFL_CIN_CLE',    // Bengals vs Browns
  'NFL_BAL_PIT',    // Ravens vs Steelers
  'NFL_PHI_WAS',    // Eagles vs Commanders
];

// Fantasy roster positions
const ROSTER_POSITIONS = [
  'QB', 'RB1', 'RB2', 'WR1', 'WR2', 'WR3', 'TE', 'FLEX', 'K', 'DEF',
  'BENCH1', 'BENCH2', 'BENCH3', 'BENCH4', 'BENCH5', 'BENCH6', 'BENCH7'
];

// Casual user: 1-2 leagues, checks periodically
export function casualUserBehavior() {
  const userId = `casual_${__VU}`;
  const leagues = generateUserLeagues(1, 2);
  
  group('Casual User - Multi-League Connection', () => {
    // Connect to primary league
    connectToLeague(userId, leagues[0], ACTIVE_GAMES[0]);
    
    sleep(30 + Math.random() * 60); // Check every 30-90 seconds
    
    // Maybe check second league
    if (leagues.length > 1 && Math.random() > 0.5) {
      connectToLeague(userId, leagues[1], ACTIVE_GAMES[1]);
      sleep(20);
    }
  });
}

// Power user: 5+ leagues, watches constantly
export function powerUserBehavior() {
  const userId = `power_${__VU}`;
  const leagues = generateUserLeagues(4, 6);
  
  group('Power User - Heavy Multi-League Monitoring', () => {
    // Connect to all leagues
    for (let i = 0; i < leagues.length; i++) {
      const game = ACTIVE_GAMES[i % ACTIVE_GAMES.length];
      connectToLeague(userId, leagues[i], game);
      sleep(2);
    }
    
    // Stay connected longer, switch between games
    sleep(120 + Math.random() * 180); // 2-5 minutes
  });
}

// My Matchups page: watching specific head-to-head matchup
export function matchupsPageBehavior() {
  const userId = `matchup_${__VU}`;
  const leagueId = `matchup_league_${__VU % 100}`;
  const game = ACTIVE_GAMES[__VU % ACTIVE_GAMES.length];
  
  group('My Matchups Page Viewer', () => {
    const url = `${WS_URL}?game_id=${game}&client_id=${userId}&league_id=${leagueId}&view=matchups`;
    
    const startTime = Date.now();
    
    const res = ws.connect(url, null, function (socket) {
      let myPlayerScores = {};
      let opponentScores = {};
      
      socket.on('open', () => {
        // Subscribe with matchup context
        socket.send(JSON.stringify({
          action: 'subscribe_matchup',
          game_id: game,
          league_id: leagueId,
          my_roster: generateFullRoster(),
          opponent_roster: generateFullRoster(),
          scoring_format: 'ppr',
        }));
      });
      
      socket.on('message', (msg) => {
        const receiveTime = Date.now();
        const data = JSON.parse(msg);
        
        if (data.type === 'delta' && data.data) {
          matchupUpdateLatency.add(receiveTime - data.timestamp);
          
          // Simulate score tracking
          if (data.data.player_id) {
            const delta = data.data.fantasy_delta?.ppr?.points_delta || 0;
            if (myPlayerScores[data.data.player_id] !== undefined) {
              myPlayerScores[data.data.player_id] += delta;
            }
            if (opponentScores[data.data.player_id] !== undefined) {
              opponentScores[data.data.player_id] += delta;
            }
          }
          
          // Check for start/sit signals (high value feature)
          if (data.data.start_sit_signal) {
            const signalLatency = receiveTime - data.timestamp;
            startSitSignalLatency.add(signalLatency);
            
            check(data, {
              'start/sit signal received': (d) => d.data.start_sit_signal !== undefined,
              'signal latency under 100ms': (d) => signalLatency < 100,
            });
          }
        }
      });
      
      // Matchup viewers stay engaged longer
      sleep(180 + Math.random() * 300); // 3-8 minutes
      socket.close();
    });
    
    check(res, {
      'matchups page connected': (r) => r && r.status === 101,
    });
  });
}

// Roster update storm: waivers, trades, lineup changes
export function rosterUpdateStorm() {
  const userId = `roster_${__VU}`;
  const leagueId = `roster_league_${__VU % 50}`;
  
  group('Roster Update Storm', () => {
    const updates = [];
    
    // Generate multiple roster changes
    for (let i = 0; i < 3; i++) {
      updates.push({
        user_id: userId,
        league_id: leagueId,
        action: Math.random() > 0.5 ? 'set_lineup' : 'add_player',
        position: ROSTER_POSITIONS[Math.floor(Math.random() * ROSTER_POSITIONS.length)],
        player_id: `PLAYER_${Math.floor(Math.random() * 100)}`,
        timestamp: Date.now(),
      });
    }
    
    const startTime = Date.now();
    
    // Send roster updates via API
    const res = http.post(
      `${BASE_URL}/api/roster/update`,
      JSON.stringify({ updates }),
      {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${__ENV.API_TOKEN || 'test-token'}`,
        },
      }
    );
    
    const syncTime = Date.now() - startTime;
    rosterSyncLatency.add(syncTime);
    
    check(res, {
      'roster update accepted': (r) => r.status === 200,
      'roster sync under 200ms': (r) => syncTime < 200,
    });
    
    multiLeagueUpdateRate.add(res.status === 200);
  });
}

// Helper functions
function connectToLeague(userId, leagueId, gameId) {
  const url = `${WS_URL}?game_id=${gameId}&client_id=${userId}&league_id=${leagueId}`;
  
  const res = ws.connect(url, null, function (socket) {
    socket.on('open', () => {
      socket.send(JSON.stringify({
        action: 'subscribe',
        games: [gameId],
        league_id: leagueId,
        scoring_format: 'ppr',
        roster: generateFullRoster(),
      }));
    });
    
    socket.on('message', (msg) => {
      const data = JSON.parse(msg);
      if (data.type === 'delta') {
        // Process update
      }
    });
    
    // Short connection for casual users
    sleep(30 + Math.random() * 30);
    socket.close();
  });
  
  return res;
}

function generateUserLeagues(min, max) {
  const count = min + Math.floor(Math.random() * (max - min + 1));
  return Array(count).fill(null).map((_, i) => `league_${__VU}_${i}`);
}

function generateFullRoster() {
  const roster = {};
  const players = generatePlayerPool();
  
  ROSTER_POSITIONS.forEach((pos, i) => {
    roster[pos] = players[i] || null;
  });
  
  return roster;
}

function generatePlayerPool() {
  const players = [];
  const positions = ['QB', 'RB', 'RB', 'WR', 'WR', 'WR', 'TE', 'FLEX', 'K', 'DEF'];
  const benchPositions = ['RB', 'RB', 'WR', 'WR', 'TE', 'QB', 'WR'];
  
  // Starters
  positions.forEach((pos) => {
    players.push({
      id: `PLAYER_${Math.floor(Math.random() * 500)}`,
      name: `Player ${Math.floor(Math.random() * 500)}`,
      position: pos,
      projected_points: generatePositionProjection(pos),
    });
  });
  
  // Bench
  benchPositions.forEach((pos) => {
    players.push({
      id: `BENCH_${Math.floor(Math.random() * 500)}`,
      name: `Bench ${Math.floor(Math.random() * 500)}`,
      position: pos,
      projected_points: generatePositionProjection(pos) * 0.7,
    });
  });
  
  return players;
}

function generatePositionProjection(pos) {
  const projections = {
    'QB': 18.5,
    'RB': 12.3,
    'WR': 11.8,
    'TE': 8.5,
    'FLEX': 10.2,
    'K': 8.0,
    'DEF': 6.5,
  };
  return projections[pos] || 10.0;
}

// Test setup
export function setup() {
  console.log('=== FantasyPros Load Test: Real User Patterns ===');
  console.log(`Active Games: ${ACTIVE_GAMES.length}`);
  console.log(`Target Casual Users: 2,000`);
  console.log(`Target Power Users: 500`);
  console.log(`Target Matchup Viewers: 1,000`);
  console.log('=================================================');
  
  return {
    startTime: Date.now(),
    activeGames: ACTIVE_GAMES.length,
    totalExpectedUsers: 3500,
  };
}

export function teardown(data) {
  const duration = (Date.now() - data.startTime) / 1000 / 60;
  console.log('');
  console.log('=== FantasyPros Pattern Test Complete ===');
  console.log(`Duration: ${duration.toFixed(1)} minutes`);
  console.log(`Active Games: ${data.activeGames}`);
  console.log(`Expected Users: ${data.totalExpectedUsers}`);
  console.log('=========================================');
}
