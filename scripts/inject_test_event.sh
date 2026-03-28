#!/bin/bash
# Script to inject test fantasy events into Kinesis
# Run: chmod +x scripts/inject_test_event.sh

GAME_ID=${1:-"NFL_101"}
PLAYER_ID=${2:-"MAHOMES_15"}
PLAYER_NAME=${3:-"Patrick Mahomes"}

echo "Injecting test fantasy events for $PLAYER_NAME..."

aws kinesis put-record \
    --stream-name blitz-data-stream \
    --partition-key "$GAME_ID" \
    --data $(echo '{
        "game_id": "'"$GAME_ID"'",
        "player_id": "'"$PLAYER_ID"'",
        "player_name": "'"$PLAYER_NAME"'",
        "timestamp": '$(date +%s%3N)',
        "stats": {
            "passing_yards": 45,
            "passing_tds": 1,
            "receptions": 0
        },
        "projected_points": 22.4,
        "scoring_format": "ppr"
    }' | base64)

echo "✅ Test event injected"
