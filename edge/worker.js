/**
 * Blitz-Scale Edge Worker - Cloudflare Durable Objects Implementation
 * 
 * Provides real-time WebSocket broadcasting for fantasy sports updates
 * with hibernation support for cost optimization and structured logging.
 */

// Structured logging utility
const createLogger = (requestId) => ({
  info: (msg, data = {}) => console.log(JSON.stringify({ level: 'INFO', requestId, timestamp: new Date().toISOString(), message: msg, ...data })),
  error: (msg, error, data = {}) => console.error(JSON.stringify({ level: 'ERROR', requestId, timestamp: new Date().toISOString(), message: msg, error: error?.message || error, stack: error?.stack, ...data })),
  warn: (msg, data = {}) => console.warn(JSON.stringify({ level: 'WARN', requestId, timestamp: new Date().toISOString(), message: msg, ...data })),
});

// Generate unique request ID
const generateRequestId = () => `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

// 1. Durable Object for Real-Time Game State Management
export class GameTrackerDO {
  constructor(state, env) {
    this.state = state;
    this.env = env;
    // Sessions will be restored from hibernation automatically
    this.sessions = new Map(); // Map<webSocket, {connectedAt, clientInfo, lastPing}>
    this.gameId = null; // Will be set on first request
    this.messageCount = 0;
    this.lastActivity = Date.now();
    this.rateLimiter = new Map(); // clientId -> {count, windowStart}
    
    // WebSocket resilience configuration
    this.PING_INTERVAL = 30000; // 30 seconds
    this.PING_TIMEOUT = 10000; // 10 seconds to respond
    this.RATE_LIMIT_WINDOW = 60000; // 1 minute
    this.RATE_LIMIT_MAX = 100; // 100 messages per minute per client
    
    // Start heartbeat checker
    this.startHeartbeatChecker();
  }
  
  // Periodic heartbeat to detect stale connections
  startHeartbeatChecker() {
    setInterval(() => {
      const now = Date.now();
      this.sessions.forEach((sessionInfo, ws) => {
        if (ws.readyState === 1) { // WebSocket.OPEN
          // Check if client missed ping
          if (sessionInfo.lastPing && (now - sessionInfo.lastPing) > this.PING_INTERVAL + this.PING_TIMEOUT) {
            console.warn(`Client ${sessionInfo.clientId} missed ping, closing connection`);
            ws.close(1001, 'Ping timeout');
            this.sessions.delete(ws);
          } else {
            // Send ping
            try {
              ws.send(JSON.stringify({ type: 'ping', timestamp: now }));
            } catch (e) {
              console.error(`Failed to send ping to ${sessionInfo.clientId}`, e);
            }
          }
        }
      });
    }, this.PING_INTERVAL);
  }
  
  // Rate limiting check
  checkRateLimit(clientId) {
    const now = Date.now();
    const windowStart = Math.floor(now / this.RATE_LIMIT_WINDOW) * this.RATE_LIMIT_WINDOW;
    
    if (!this.rateLimiter.has(clientId)) {
      this.rateLimiter.set(clientId, { count: 1, windowStart });
      return true;
    }
    
    const limiter = this.rateLimiter.get(clientId);
    
    // Reset if new window
    if (limiter.windowStart !== windowStart) {
      limiter.count = 1;
      limiter.windowStart = windowStart;
      return true;
    }
    
    // Check limit
    if (limiter.count >= this.RATE_LIMIT_MAX) {
      return false;
    }
    
    limiter.count++;
    return true;
  }

  async fetch(request) {
    const requestId = generateRequestId();
    const logger = createLogger(requestId);
    const url = new URL(request.url);
    
    // Extract gameId from DO name on first request
    if (!this.gameId) {
      this.gameId = this.state.id.toString();
    }

    // WebSocket Connection from Client
    if (url.pathname === "/connect") {
      const clientInfo = {
        clientId: url.searchParams.get("client_id") || 'anonymous',
        userAgent: request.headers.get('User-Agent') || 'unknown',
        connectedAt: new Date().toISOString()
      };
      
      logger.info("WebSocket connection request", { gameId: this.gameId, clientInfo });

      try {
        const [client, server] = Object.values(new WebSocketPair());
        server.accept();
        
        // Store session metadata with ping tracking
        this.sessions.set(server, { ...clientInfo, lastPing: Date.now(), reconnectAttempts: 0 });
        this.lastActivity = Date.now();
        
        // Handle close with cleanup
        server.addEventListener("close", (event) => {
          logger.info("WebSocket closed", { gameId: this.gameId, clientId: clientInfo.clientId, code: event.code, reason: event.reason });
          this.sessions.delete(server);
          this.lastActivity = Date.now();
        });

        // Handle errors
        server.addEventListener("error", (error) => {
          logger.error("WebSocket error", error, { gameId: this.gameId, clientId: clientInfo.clientId });
          this.sessions.delete(server);
        });
        
        // Handle pong responses for connection health
        server.addEventListener("message", (event) => {
          try {
            const data = JSON.parse(event.data);
            
            // Handle pong response
            if (data.type === 'pong') {
              const session = this.sessions.get(server);
              if (session) {
                session.lastPing = Date.now();
                logger.debug("Pong received", { clientId: clientInfo.clientId, latency: Date.now() - data.timestamp });
              }
            }
            
            // Handle subscription messages with rate limiting
            if (data.type === 'subscribe') {
              if (!this.checkRateLimit(clientInfo.clientId)) {
                logger.warn("Rate limit exceeded", { clientId: clientInfo.clientId });
                server.send(JSON.stringify({ type: 'error', message: 'Rate limit exceeded. Please slow down.' }));
                return;
              }
              
              logger.info("Subscription update", { clientId: clientInfo.clientId, games: data.games });
            }
          } catch (e) {
            logger.error("Failed to parse message", e, { clientId: clientInfo.clientId });
          }
        });

        // Send welcome message with current game state from KV
        try {
          const currentState = await this.env.GAME_STATE_KV.get(`state:${this.gameId}`);
          if (currentState) {
            server.send(JSON.stringify({
              type: 'initial_state',
              data: JSON.parse(currentState),
              timestamp: Date.now()
            }));
            logger.info("Sent initial state to client", { gameId: this.gameId, clientId: clientInfo.clientId });
          }
        } catch (kvError) {
          logger.warn("Failed to fetch initial state from KV", { error: kvError.message, gameId: this.gameId });
        }

        logger.info("WebSocket connected", { gameId: this.gameId, clientId: clientInfo.clientId, totalSessions: this.sessions.size });
        
        return new Response(null, { status: 101, webSocket: client });
        
      } catch (error) {
        logger.error("Failed to establish WebSocket", error, { gameId: this.gameId });
        return new Response("WebSocket error", { status: 500 });
      }
    }

    // Broadcast update from Webhook
    if (url.pathname === "/broadcast") {
      try {
        const update = await request.json();
        const payload = JSON.stringify({
          type: 'delta',
          data: update,
          timestamp: Date.now()
        });
        
        this.lastActivity = Date.now();
        
        // Track broadcast metrics
        let successCount = 0;
        let failCount = 0;
        
        this.sessions.forEach((clientInfo, ws) => {
          try {
            if (ws.readyState === 1) { // WebSocket.OPEN
              ws.send(payload);
              successCount++;
            } else {
              // Remove stale connections
              this.sessions.delete(ws);
              failCount++;
            }
          } catch (e) {
            logger.error("Broadcast send failed", e, { clientId: clientInfo.clientId });
            this.sessions.delete(ws);
            failCount++;
          }
        });

        this.messageCount++;
        
        logger.info("Broadcast completed", { 
          gameId: this.gameId, 
          successCount, 
          failCount, 
          totalSessions: this.sessions.size,
          messageCount: this.messageCount 
        });
        
        return new Response(JSON.stringify({ 
          success: true, 
          recipients: successCount,
          failed: failCount 
        }), { 
          headers: { 'Content-Type': 'application/json' }
        });
        
      } catch (error) {
        logger.error("Broadcast failed", error, { gameId: this.gameId });
        return new Response(JSON.stringify({ error: "Broadcast failed" }), { 
          status: 500,
          headers: { 'Content-Type': 'application/json' }
        });
      }
    }

    // Health check endpoint
    if (url.pathname === "/health") {
      return new Response(JSON.stringify({
        status: 'healthy',
        gameId: this.gameId,
        sessions: this.sessions.size,
        messageCount: this.messageCount,
        lastActivity: this.lastActivity,
        uptime: Date.now() - (this.state.createdAt || Date.now())
      }), {
        headers: { 'Content-Type': 'application/json' }
      });
    }

    return new Response("Not Found", { status: 404 });
  }

  // Hibernation support - called when DO is about to hibernate
  async webSocketClose(ws) {
    const clientInfo = this.sessions.get(ws);
    if (clientInfo) {
      this.sessions.delete(ws);
    }
    this.lastActivity = Date.now();
  }
}

// 2. Main Worker Entry Point
export default {
  async fetch(request, env) {
    const requestId = generateRequestId();
    const logger = createLogger(requestId);
    const url = new URL(request.url);
    
    logger.info("Request received", { path: url.pathname, method: request.method });

    // Client WebSocket Handshake
    if (url.pathname === "/realtime") {
      const gameId = url.searchParams.get("game_id");
      const leagueId = url.searchParams.get("league_id");
      const clientId = url.searchParams.get("client_id");
      
      if (!gameId) {
        logger.warn("Missing game_id parameter");
        return new Response("Missing game_id", { status: 400 });
      }

      try {
        // Support multi-league subscriptions by combining game_id and league_id
        const doId = leagueId ? `${gameId}:${leagueId}` : gameId;
        const id = env.GAME_TRACKER_DO.idFromName(doId);
        const obj = env.GAME_TRACKER_DO.get(id);
        
        // Build connection URL with client metadata
        const connectUrl = new URL(request.url);
        connectUrl.pathname = "/connect";
        if (clientId) {
          connectUrl.searchParams.set("client_id", clientId);
        }
        
        logger.info("Forwarding to Durable Object", { gameId, leagueId, doId });
        
        // Forward request to Durable Object
        return obj.fetch(new Request(connectUrl.toString(), request));
        
      } catch (error) {
        logger.error("Failed to connect to Durable Object", error, { gameId });
        return new Response("Connection failed", { status: 500 });
      }
    }

    // Webhook Ingest from AWS Lambda
    if (url.pathname === "/webhook/update" && request.method === "POST") {
      const authHeader = request.headers.get("Authorization");
      if (authHeader !== `Bearer ${env.WEBHOOK_SECRET_TOKEN}`) {
        logger.warn("Unauthorized webhook request", { authHeader: authHeader?.slice(0, 20) });
        return new Response("Unauthorized", { status: 401 });
      }

      try {
        const payload = await request.json();
        const events = payload.events || [];
        
        logger.info("Processing webhook batch", { eventCount: events.length });

        const results = {
          processed: 0,
          failed: 0,
          kvUpdates: 0,
          broadcasts: 0
        };

        for (const event of events) {
          // Enhanced Schema Validation
          if (!event.game_id || !event.player_id) {
            logger.error("Invalid event format received", null, { event });
            results.failed++;
            continue;
          }

          const gameId = event.game_id;
          const leagueId = event.league_id; // Optional multi-tenant support
          
          try {
            // 1. Update Persistent Edge Cache (KV) with TTL
            const kvKey = leagueId ? `state:${gameId}:${leagueId}` : `state:${gameId}`;
            await env.GAME_STATE_KV.put(kvKey, JSON.stringify(event), { 
              expirationTtl: 3600 // 1 hour TTL
            });
            results.kvUpdates++;

            // 2. Trigger Real-Time Broadcast via Durable Object
            const doId = leagueId ? `${gameId}:${leagueId}` : gameId;
            const id = env.GAME_TRACKER_DO.idFromName(doId);
            const obj = env.GAME_TRACKER_DO.get(id);
            
            const broadcastResp = await obj.fetch(new Request("http://do/broadcast", {
              method: "POST",
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(event)
            }));
            
            if (broadcastResp.ok) {
              results.broadcasts++;
            }
            
            results.processed++;
            
          } catch (eventError) {
            logger.error("Failed to process event", eventError, { gameId, player_id: event.player_id });
            results.failed++;
          }
        }

        logger.info("Webhook processing complete", results);

        return new Response(JSON.stringify({ 
          success: true, 
          count: events.length,
          results 
        }), {
          headers: { 'Content-Type': 'application/json' }
        });
        
      } catch (error) {
        logger.error("Webhook processing failed", error);
        return new Response(JSON.stringify({ error: "Processing failed" }), { 
          status: 500,
          headers: { 'Content-Type': 'application/json' }
        });
      }
    }

    // Health check endpoint
    if (url.pathname === "/health") {
      return new Response(JSON.stringify({
        status: 'healthy',
        service: 'blitz-scale-edge-hub',
        timestamp: Date.now()
      }), {
        headers: { 'Content-Type': 'application/json' }
      });
    }

    return new Response("Blitz-Scale Edge Hub Active", { status: 200 });
  }
};
