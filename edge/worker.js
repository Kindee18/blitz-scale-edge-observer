export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // 1. WebSocket Endpoint for Clients
    if (url.pathname === "/realtime") {
      if (request.headers.get("Upgrade") !== "websocket") {
        return new Response("Expected Upgrade: websocket", { status: 426 });
      }

      const [client, server] = Object.values(new WebSocketPair());
      const clientId = url.searchParams.get("client_id") || crypto.randomUUID();

      server.accept();
      server.addEventListener("message", async (msg) => {
        try {
          const data = JSON.parse(msg.data);
          if (data.action === "subscribe") {
            // In a real implementation using Durable Objects, we'd route this
            // connection to the Game's Durable Object to manage broadcasting.
            // For KV-based simple caching, we can just send the latest state immediately:
            for (const game of data.games) {
              const cachedState = await env.GAME_STATE_KV.get(`state:${game}`);
              if (cachedState) {
                server.send(cachedState);
              }
            }
          }
        } catch (e) {
          console.error("WebSocket message error", e);
        }
      });

      return new Response(null, {
        status: 101,
        webSocket: client,
      });
    }

    // 2. Webhook Endpoint for Kinesis Lambda Delta Processor
    if (url.pathname === "/webhook/update" && request.method === "POST") {
      const authHeader = request.headers.get("Authorization");
      if (authHeader !== `Bearer ${env.WEBHOOK_SECRET_TOKEN}`) {
        return new Response("Unauthorized", { status: 401 });
      }

      try {
        const payload = await request.json();
        const events = payload.events || [];

        // Broadcast to WebSockets & Update KV Cache
        for (const event of events) {
          const { game_id, player_id, delta } = event;
          
          // Using KV for fast read/edges
          // We put the latest update in KV so late-joiners get the freshest data
          await env.GAME_STATE_KV.put(`state:${game_id}`, JSON.stringify(event), {
            expirationTtl: 3600 // Expire after an hour
          });

          // In a Durable Objects architecture, we would broadcast the delta to
          // all connected websockets subscribed to this game_id here.
          // e.g. env.GAME_TRACKER_DO.get(id).fetch("http://.../broadcast", { body: event })
        }

        return new Response(JSON.stringify({ success: true, processed: events.length }), {
          headers: { "Content-Type": "application/json" }
        });

      } catch (err) {
        return new Response("Bad Request", { status: 400 });
      }
    }

    return new Response("Not Found", { status: 404 });
  }
};
