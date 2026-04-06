#!/bin/bash
set -e

export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
ENDPOINT="http://localhost:4566"

echo "Waiting for LocalStack to be ready..."
until curl -s "$ENDPOINT/_localstack/health" | grep -q "\"kinesis\": \"\(running\|available\|ready\)\""; do
  sleep 2
done
echo "LocalStack is ready!"

echo "Creating DynamoDB table..."
aws --endpoint-url=$ENDPOINT dynamodb create-table \
    --table-name blitz-game-state-versions \
    --attribute-definitions AttributeName=state_id,AttributeType=S \
    --key-schema AttributeName=state_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST 2>/dev/null || echo "Table likely exists."

echo "Creating Kinesis stream..."
aws --endpoint-url=$ENDPOINT kinesis create-stream \
    --stream-name blitz-data-stream \
    --shard-count 1 2>/dev/null || echo "Stream likely exists."

echo "Setup complete."
