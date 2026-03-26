# Edge Optimization Strategy

## Overview
To deliver sub-100ms real-time updates globally under massive load (e.g., NFL Sundays), the Blitz-Scale Edge Observer relies on pushing data to the network edge rather than relying on origin polling.

## Caching Strategy
1. **Cloudflare KV (Key-Value) Datastore**:
   - As our `delta_processor_lambda.py` computes incremental state changes, it pushes them to the Cloudflare Worker `webhook/update` endpoint.
   - The worker immediately caches the event inside a Cloudflare KV namespace (`GAME_STATE_KV`). KV is eventually consistent but read-optimized at all edge locations.
   - When new mobile clients connect or reconnect via WebSockets, they instantly receive the cached state from the nearest physical data center before joining the live broadcast stream. This prevents a "thundering herd" problem on the origin database.

## Latency Optimization
1. **WebSocket Persistence**:
   - Clients maintain long-lived WebSocket connections terminating at the Cloudflare Edge location closest to them rather than traversing the internet back to AWS.
   - AWS only sends a single Delta payload to Cloudflare, which then uses its internal backbone to broadcast it to connected edge nodes and subsequently down to end users.
   
2. **Minimal Payload (Deltas)**:
   - Instead of sending 500KB of complete game state JSON every second, AWS Lambda compares current state with Redis and only emits JSON patches (e.g., `{"Patrick Mahomes": {"pass_yards": 310}}`). This reduces network propagation delay globally.
   - Reduced serialization overhead and faster TLS frame transmission yields 20-40ms savings.

3. **Multi-Region AWS Backbone**:
   - The Terraform infrastructure allows `lambda_delta_processor` to run in multiple Availability Zones and Regions to guarantee high availability.
