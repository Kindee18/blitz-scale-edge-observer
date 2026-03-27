// 1. Durable Object for Real-Time Game State Management
export class GameTrackerDO {
  constructor(state, env) {
    this.state = state;
    this.sessions = new Set();
  }

  async fetch(request) {
    const url = new URL(request.url);

    // WebSocket Connection from Client
    if (url.pathname === "/connect") {
      const [client, server] = Object.values(new WebSocketPair());
      server.accept();
      
      this.sessions.add(server);
      server.addEventListener("close", () => this.sessions.delete(server));

      return new Response(null, { status: 101, webSocket: client });
    }

    // Broadcast update from Webhook
    if (url.pathname === "/broadcast") {
      const update = await request.json();
      const payload = JSON.stringify(update);
      
      this.sessions.forEach(s => {
        try {
          s.send(payload);
        } catch (e) {
          this.sessions.delete(s);
        }
      });
      
      return new Response("OK");
    }

    return new Response("Not Found", { status: 404 });
  }
}

// 2. Main Worker Entry Point
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Client WebSocket Handshake
    if (url.pathname === "/realtime") {
      const gameId = url.searchParams.get("game_id");
      if (!gameId) return new Response("Missing game_id", { status: 400 });

      const id = env.GAME_TRACKER_DO.idFromName(gameId);
      const obj = env.GAME_TRACKER_DO.get(id);
      
      // Forward request to Durable Object
      return obj.fetch(new Request(request.url.replace("/realtime", "/connect"), request));
    }

    // Webhook Ingest from AWS Lambda
    if (url.pathname === "/webhook/update" && request.method === "POST") {
      const authHeader = request.headers.get("Authorization");
      if (authHeader !== `Bearer ${env.WEBHOOK_SECRET_TOKEN}`) {
        return new Response("Unauthorized", { status: 401 });
      }

      const payload = await request.json();
      const events = payload.events || [];

      for (const event of events) {
        // Enforce Minimal Schema Validation
        if (!event.game_id || !event.player_id || !event.delta) {
          console.error("Invalid event format received", event);
          continue;
        }

        const gameId = event.game_id;
        
        // 1. Update Persistent Edge Cache (KV)
        await env.GAME_STATE_KV.put(`state:${gameId}`, JSON.stringify(event), { expirationTtl: 3600 });

        // 2. Trigger Real-Time Broadcast via Durable Object
        const id = env.GAME_TRACKER_DO.idFromName(gameId);
        const obj = env.GAME_TRACKER_DO.get(id);
        await obj.fetch(new Request("http://do/broadcast", {
          method: "POST",
          body: JSON.stringify(event)
        }));
      }

      return new Response(JSON.stringify({ success: true, count: events.length }));
    }

    return new Response("Blitz-Scale Edge Hub Active", { status: 200 });
  }
};
