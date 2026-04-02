"""Enhanced Fantasy Sports Client Simulator.

Simulates FantasyPros mobile app clients connecting to the edge,
receiving real-time fantasy score updates, and displaying
fantasy roster performance with start/sit signals.
"""

import asyncio
import contextlib
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:
    import websockets
except ImportError:
    logging.warning("websockets module not installed. Run: pip install websockets")
    websockets = None

# Configure logging
logger = logging.getLogger("FantasyClientSim")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
)
logger.addHandler(handler)

# Configuration
EDGE_WS_URL = os.getenv(
    "EDGE_WS_URL", "wss://blitz-edge-observer.kindsonegbule15.workers.dev/realtime"
)


@dataclass
class FantasyPlayer:
    """Represents a player on a fantasy roster."""

    player_id: str
    player_name: str
    position: str  # QB, RB, WR, TE, K, DST
    current_points: float = 0.0
    projected_points: float = 0.0
    scoring_format: str = "ppr"
    last_update: int = 0

    def update_points(self, new_points: float):
        """Update player points and track delta."""
        delta = new_points - self.current_points
        self.current_points = new_points
        return delta


@dataclass
class FantasyRoster:
    """Represents a user's fantasy roster for a specific league."""

    league_id: str
    user_id: str
    scoring_format: str = "ppr"  # ppr, half_ppr, standard
    players: Dict[str, FantasyPlayer] = field(default_factory=dict)
    total_points: float = 0.0
    total_projected: float = 0.0

    def add_player(self, player: FantasyPlayer):
        """Add a player to the roster."""
        self.players[player.player_id] = player
        self.total_projected += player.projected_points

    def update_player(self, player_id: str, new_points: float) -> Optional[float]:
        """Update a player's points and recalculate total."""
        if player_id not in self.players:
            return None

        player = self.players[player_id]
        delta = player.update_points(new_points)
        self.total_points += delta
        player.last_update = int(time.time() * 1000)
        return delta

    def display_summary(self):
        """Display current roster status."""
        print("\n" + "=" * 60)
        print(f"Fantasy Roster: {self.league_id} | User: {self.user_id}")
        print(
            f"Scoring: {self.scoring_format.upper()} | Total: {self.total_points:.1f} pts"
        )
        print(
            f"vs Projection: {self.total_projected:.1f} pts ({self.total_points - self.total_projected:+.1f})"
        )
        print("-" * 60)

        for position in ["QB", "RB", "WR", "TE", "FLEX", "K", "DST"]:
            players_in_pos = [
                p for p in self.players.values() if p.position == position
            ]
            for player in players_in_pos:
                vs_proj = player.current_points - player.projected_points
                status = "🔥" if vs_proj > 5 else "⚠️" if vs_proj < -5 else "➡️"
                print(
                    f"{status} {position}: {player.player_name:<20} {player.current_points:>5.1f} pts (proj {player.projected_points:.1f})"
                )

        print("=" * 60 + "\n")


class FantasyClientSimulator:
    """Simulates a FantasyPros mobile client with real-time updates."""

    def __init__(
        self,
        client_id: str,
        game_ids: List[str],
        league_id: Optional[str] = None,
        mode: str = "fantasy",
    ):
        self.client_id = client_id
        self.game_ids = game_ids
        self.league_id = league_id or f"demo_league_{client_id}"
        self.mode = mode
        self.roster: Optional[FantasyRoster] = None
        self.latency_history: List[float] = []
        self.update_count = 0
        self.start_time = time.time()
        self.last_server_timestamp = 0
        self.reconnect_attempts = 0

    def create_mock_roster(self):
        """Create a mock fantasy roster for demo purposes."""
        self.roster = FantasyRoster(
            league_id=self.league_id,
            user_id=f"user_{self.client_id}",
            scoring_format=random.choice(["ppr", "half_ppr", "standard"]),
        )

        # Mock NFL players with projections
        mock_players = [
            ("MAHOMES_15", "Patrick Mahomes", "QB", 22.5),
            ("MCCAFFREY_23", "Christian McCaffrey", "RB", 18.5),
            ("HILL_10", "Tyreek Hill", "WR", 15.2),
            ("KELCE_87", "Travis Kelce", "TE", 12.8),
            ("KUPP_10", "Cooper Kupp", "WR", 14.1),
            ("HURTS_01", "Jalen Hurts", "QB", 20.3),
            ("ADAMS_17", "Davante Adams", "WR", 13.7),
            ("TUCKER_09", "Justin Tucker", "K", 8.5),
        ]

        for pid, name, pos, proj in mock_players:
            player = FantasyPlayer(
                player_id=pid,
                player_name=name,
                position=pos,
                projected_points=proj,
                scoring_format=self.roster.scoring_format,
            )
            self.roster.add_player(player)

        logger.info(
            f"Created mock roster with {len(mock_players)} players ({self.roster.scoring_format} scoring)"
        )

    async def connect(self):
        """Connect to the edge WebSocket and handle updates."""
        if not websockets:
            logger.error("websockets module not installed. Run: pip install websockets")
            return
        while True:
            try:
                # Build connection URL with replay cursor for resumable sessions
                params = [f"client_id={self.client_id}"]
                if self.game_ids:
                    params.append(f"game_id={self.game_ids[0]}")
                if self.league_id:
                    params.append(f"league_id={self.league_id}")
                if self.last_server_timestamp > 0:
                    params.append(f"since_ts={self.last_server_timestamp}")

                url = f"{EDGE_WS_URL}?{'&'.join(params)}"
                logger.info(f"Connecting to {url}...")

                async with websockets.connect(url) as websocket:
                    self.reconnect_attempts = 0
                    logger.info(f"✅ Client {self.client_id} connected to edge")

                    subscribe_msg = {
                        "action": "subscribe",
                        "games": self.game_ids,
                        "league_id": self.league_id,
                        "mode": self.mode,
                    }
                    await websocket.send(json.dumps(subscribe_msg))
                    logger.info(f"Subscribed to games: {self.game_ids}")

                    if self.roster:
                        self.roster.display_summary()

                    async for message in websocket:
                        await self.handle_message(websocket, message)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.reconnect_attempts += 1
                backoff = min(
                    10, (2 ** min(self.reconnect_attempts, 5)) + random.uniform(0, 0.5)
                )
                logger.error(
                    f"❌ Connection error: {e} | reconnect attempt {self.reconnect_attempts} in {backoff:.1f}s"
                )
                await asyncio.sleep(backoff)

    async def handle_message(self, websocket, message: str):
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "unknown")

            # Calculate latency
            server_ts = data.get("timestamp", 0)
            if server_ts:
                latency = (time.time() * 1000) - server_ts
                self.latency_history.append(latency)
                self.update_count += 1
                self.last_server_timestamp = max(
                    self.last_server_timestamp, int(server_ts)
                )
            else:
                latency = 0

            if msg_type == "ping":
                await websocket.send(
                    json.dumps({"type": "pong", "timestamp": int(time.time() * 1000)})
                )
                return

            if msg_type == "initial_state":
                # Handle initial state for late-joiners
                logger.info("📥 Received initial state (KV cache)")

            elif msg_type in ["delta", "delta_replay"]:
                # Handle fantasy delta update
                delta_data = data.get("data", {})
                await self.handle_fantasy_delta(delta_data, latency)

            else:
                logger.info(f"📨 Message ({msg_type}): {data}")

        except json.JSONDecodeError:
            logger.warning(f"Received non-JSON message: {message[:100]}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    async def handle_fantasy_delta(self, data: Dict, latency: float):
        """Handle fantasy points delta update."""
        player_id = data.get("player_id")
        player_name = data.get("player_name", player_id)

        # Extract fantasy delta
        fantasy_delta = data.get("fantasy_delta", {})

        # Get points for our scoring format
        format_delta = (
            fantasy_delta.get(self.roster.scoring_format, {}) if self.roster else {}
        )
        points_delta = format_delta.get("points_delta", 0)
        current_points = format_delta.get("current_points", 0)

        # Check for start/sit signal
        signal = fantasy_delta.get("start_sit_signal")

        # Update roster if player is on our team
        if self.roster and player_id in self.roster.players:
            self.roster.update_player(player_id, current_points)
            new_total = self.roster.total_points

            # Display update
            emoji = "📈" if points_delta > 0 else "📉" if points_delta < 0 else "➡️"
            logger.info(
                f"{emoji} YOUR ROSTER UPDATE | {player_name} "
                f"{current_points:.1f} pts ({points_delta:+.1f}) | "
                f"Team Total: {new_total:.1f} pts | "
                f"Latency: {latency:.0f}ms"
            )

            if signal:
                logger.info(f"💡 SIGNAL: {signal}")

            # Show roster summary every 5 updates
            if self.update_count % 5 == 0:
                self.roster.display_summary()
                self.print_latency_stats()
        else:
            # Not on our roster, just log it
            logger.info(
                f"🏈 League Update | {player_name}: {current_points:.1f} pts "
                f"({points_delta:+.1f}) | Latency: {latency:.0f}ms"
            )

    def print_latency_stats(self):
        """Print latency statistics."""
        if not self.latency_history:
            return

        latencies = self.latency_history[-100:]  # Last 100 updates
        avg = sum(latencies) / len(latencies)
        p99 = sorted(latencies)[int(len(latencies) * 0.99)]

        elapsed = time.time() - self.start_time
        rate = self.update_count / elapsed if elapsed > 0 else 0

        logger.info(
            f"📊 STATS | Updates: {self.update_count} | "
            f"Avg Latency: {avg:.1f}ms | P99: {p99:.1f}ms | "
            f"Rate: {rate:.1f} updates/sec"
        )


async def run_multiple_clients(
    num_clients: int = 3,
    game_ids: List[str] = None,
    duration: int = 60,
    mode: str = "fantasy",
):
    """Run multiple concurrent fantasy clients."""
    game_ids = game_ids or ["NFL_101", "NFL_102"]

    logger.info(f"🏁 Starting {num_clients} concurrent fantasy clients...")
    logger.info(f"⏱️  Demo duration: {duration} seconds")
    logger.info(f"🎮 Mode: {mode}")

    clients = []
    for i in range(num_clients):
        client = FantasyClientSimulator(
            client_id=f"demo_user_{i}",
            game_ids=game_ids,
            league_id=f"fantasy_league_{i % 3}",  # 3 leagues
            mode=mode,
        )
        client.create_mock_roster()
        clients.append(client)

    # Run clients concurrently with timeout
    tasks = [asyncio.create_task(client.connect()) for client in clients]

    try:
        await asyncio.sleep(duration)
    except asyncio.TimeoutError:
        logger.info("⏰ Demo duration reached, stopping clients...")
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # Print final stats
    logger.info("\n" + "=" * 60)
    logger.info("FINAL STATISTICS")
    logger.info("=" * 60)

    for client in clients:
        if client.latency_history:
            avg = sum(client.latency_history) / len(client.latency_history)
            logger.info(
                f"Client {client.client_id}: "
                f"{client.update_count} updates | "
                f"{avg:.1f}ms avg latency | "
                f"League: {client.league_id}"
            )


def main():
    """Main entry point."""
    import argparse

    global EDGE_WS_URL

    parser = argparse.ArgumentParser(description="FantasyPros Client Simulator")
    parser.add_argument(
        "--clients", type=int, default=3, help="Number of concurrent clients"
    )
    parser.add_argument(
        "--duration", type=int, default=60, help="Demo duration in seconds"
    )
    parser.add_argument(
        "--mode",
        choices=["fantasy", "basic"],
        default="fantasy",
        help="Simulation mode",
    )
    parser.add_argument(
        "--games",
        nargs="+",
        default=["NFL_101", "NFL_102"],
        help="Game IDs to subscribe to",
    )
    parser.add_argument("--url", default=EDGE_WS_URL, help="WebSocket URL")

    args = parser.parse_args()

    # Update global URL if provided
    EDGE_WS_URL = args.url

    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║           FantasyPros Client Simulator                       ║
    ║           Blitz-Scale Edge Observer Demo                     ║
    ╠══════════════════════════════════════════════════════════════╣
    ║  Simulating real-time fantasy score updates                  ║
    ║  with sub-100ms latency and roster tracking                  ║
    ╚══════════════════════════════════════════════════════════════╝
    """)

    try:
        asyncio.run(
            run_multiple_clients(
                num_clients=args.clients,
                game_ids=args.games,
                duration=args.duration,
                mode=args.mode,
            )
        )
    except KeyboardInterrupt:
        logger.info("\n👋 Demo stopped by user")
    except Exception as e:
        logger.error(f"Demo error: {e}")


if __name__ == "__main__":
    main()
