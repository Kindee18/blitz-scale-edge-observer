<!-- markdownlint-disable MD009 MD022 MD031 MD032 MD036 MD051 MD060 -->

# Blitz-Scale Edge Observer - Operational Runbook

## Table of Contents

1. [Overview](#overview)
2. [Game-Day Playbook](#game-day-playbook)
3. [Deployment Procedures](#deployment-procedures)
4. [Common Operations](#common-operations)
5. [Troubleshooting](#troubleshooting)
6. [Failure Scenarios](#failure-scenarios)
7. [Cost Monitoring](#cost-monitoring)
8. [Security & Compliance](#security--compliance)

---

## Overview

This runbook covers operational procedures for the Blitz-Scale Edge Observer infrastructure, designed to handle real-time fantasy sports scoring updates for FantasyPros Game Day.

**Key Components:**

- **Predictive Scaler:** EKS pre-warming for NFL Sunday spikes
- **Delta Processor:** Kinesis -> Lambda -> Fantasy points calculation
- **Edge Worker:** Cloudflare WebSocket broadcasting
- **FinOps Filter:** Log cost optimization (93% reduction)

---

## Game-Day Playbook

### NFL Sunday 1PM ET Kickoff - T-60 Minutes

```bash
# Pre-game system health check
echo "=== Pre-Game Health Check ==="

# 1. Verify predictive scaler is scheduled
echo "Checking EventBridge rules..."
aws events list-rules --name-prefix blitz-scaler

# 2. Check EKS cluster health
echo "Checking EKS nodes..."
aws eks describe-cluster --name blitz-edge-cluster --query 'cluster.status'
kubectl get nodes -o wide

# 3. Verify Kinesis stream capacity
echo "Checking Kinesis shards..."
aws kinesis describe-stream --stream-name fantasy-sports-realtime-ingest \
  --query 'StreamDescription.Shards' | jq length

# 4. Test WebSocket endpoint
echo "Testing WebSocket health..."
curl -s https://blitz-edge-observer.kindsonegbule15.workers.dev/health | jq '.status'

# 5. Check Redis connection pool
echo "Checking Redis..."
redis-cli -u $REDIS_URL ping

# 6. Verify CloudWatch alarms are active
echo "Checking alarms..."
aws cloudwatch describe-alarms --state-value ALARM

echo "=== Pre-Game Check Complete ==="
```

### T-30 Minutes - Predictive Scaling Verification

```bash
# Manually trigger scaler to verify pre-warming
make invoke-scaler

# Monitor scaling progress
echo "Monitoring Karpenter node provisioning..."
watch -n 5 'kubectl get nodes -l karpenter.sh/provisioner-name'

# Verify pause pods are running
echo "Checking pause pods..."
kubectl get deployments spike-buffer -n default

# Expected: 10 pause pods should be running
```

### T-0 Kickoff - Real-Time Monitoring

```bash
# Open multiple monitoring windows

# Window 1: Delta Processor logs
make logs-processor

# Window 2: CloudWatch metrics dashboard
open "https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=Blitz-Scale-Observer-Ops"

# Window 3: WebSocket connection metrics
wrangler tail

# Window 4: Kinesis metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/Kinesis \
  --metric-name IncomingRecords \
  --dimensions Name=StreamName,Value=fantasy-sports-realtime-ingest \
  --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --statistics Sum
```

### Touchdown Drive Surge Response

When fantasy traffic spikes during critical game moments:

```bash
# 1. Check current connection count
curl -s https://blitz-edge-observer.kindsonegbule15.workers.dev/health | jq '.sessions'

# 2. Verify auto-scaling is responding
echo "Current Lambda concurrency:"
aws lambda get-function-concurrency --function-name fantasy-data-delta-processor

# 3. Monitor for throttling
echo "Checking for throttling..."
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Throttles \
  --dimensions Name=FunctionName,Value=fantasy-data-delta-processor \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --statistics Sum

# 4. Emergency scale-up if needed
# (Only if predictive scaling failed)
aws lambda put-function-concurrency \
  --function-name fantasy-data-delta-processor \
  --reserved-concurrent-executions 1000
```

---

## Deployment Procedures

### Full Stack Deployment

```bash
# 1. Ensure prerequisites
aws sts get-caller-identity  # Verify AWS access
terraform version            # Verify v1.6.0+
node --version               # Verify v18+

# 2. Deploy everything
make deploy-all

# 3. Or step by step:
make deploy-backend  # EKS + Kinesis
make deploy-edge     # Cloudflare Worker
```

### Emergency Rollback

```bash
# Terraform rollback
cd terraform/eks
terraform state list
terraform apply -target=module.eks -var='cluster_version=1.27'

# Cloudflare rollback
cd edge
wrangler rollback
```

---

## Common Operations

### Pre-Game Checklist (T-30 mins)

1. Verify `scheduled_scaler_lambda` ran successfully
2. Check EKS Node count (Karpenter 'pause' pods provisioning)
3. Verify Redis CPU < 20%
4. Test WebSocket endpoint

### View Logs & Metrics

```bash
# Predictive Scaler logs
make logs-scaler

# Delta Processor logs
make logs-processor

# Manual trigger
make invoke-scaler
```

---

## Troubleshooting

### Issue: High Delta Latency (>200ms)

1. **Check**: Lambda Duration in CloudWatch
2. **Action**: Increase Kinesis Shard count if throttling
3. **Check**: Redis connection pool errors

### Issue: Edge Webhook 429s/503s

1. **Check**: Cloudflare Worker CPU limits
2. **Verify**: `WEBHOOK_SECRET_TOKEN` hasn't expired
3. **Test**: Direct Lambda invocation

### Issue: Predictive Scaler Lock Contention

**Resolution:** Normal behavior - only one scaler runs per window. Check for stuck locks:

```bash
aws dynamodb scan --table-name blitz-scaling-locks
```

---

## Failure Scenarios

### Scenario: Redis Outage (ElastiCache Failover)

**Impact:** Delta Processor falls back to DynamoDB, ~50ms additional latency

**Detection:**

```bash
# Check Redis CloudWatch metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/ElastiCache \
  --metric-name EngineCPUUtilization \
  --dimensions Name=CacheClusterId,Value=blitz-redis \
  --statistics Average \
  --period 300

# Check Redis connection errors in Lambda logs
aws logs filter-log-events \
  --log-group-name /aws/lambda/fantasy-data-delta-processor \
  --filter-pattern "RedisConnectionError" \
  --start-time $(date -d '5 minutes ago' +%s)000
```

**Response:**

```bash
# 1. Verify automatic failover to replica
aws elasticache describe-cache-clusters \
  --cache-cluster-id blitz-redis \
  --show-cache-node-info

# 2. Check if DynamoDB fallback is active
aws dynamodb scan --table-name blitz-game-state-versions --max-items 5

# 3. If Redis completely unavailable, increase Lambda timeout temporarily
aws lambda update-function-configuration \
  --function-name fantasy-data-delta-processor \
  --timeout 30

# 4. Monitor for recovery
watch -n 10 'aws elasticache describe-events --source-identifier blitz-redis --max-records 5'
```

**Recovery:** Redis typically recovers in 2-4 minutes with Multi-AZ failover

---

### Scenario: Kinesis Processing Delay

**Impact:** Increased latency in fantasy updates, potential data backlog

**Detection:**

```bash
# Check Kinesis iterator age (ms behind realtime)
aws cloudwatch get-metric-statistics \
  --namespace AWS/Kinesis \
  --metric-name GetRecords.IteratorAgeMilliseconds \
  --dimensions Name=StreamName,Value=fantasy-sports-realtime-ingest \
  --statistics Average \
  --period 60

# Check Lambda concurrent executions
aws lambda get-function-concurrency --function-name fantasy-data-delta-processor

# Check for throttling
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Throttles \
  --dimensions Name=FunctionName,Value=fantasy-data-delta-processor \
  --statistics Sum \
  --period 60
```

**Response:**

```bash
# 1. Increase Kinesis shard count for parallel processing
aws kinesis update-shard-count \
  --stream-name fantasy-sports-realtime-ingest \
  --target-shard-count 20 \
  --scaling-type UNIFORM_SCALING

# 2. Increase Lambda concurrency limit
aws lambda put-function-concurrency \
  --function-name fantasy-data-delta-processor \
  --reserved-concurrent-executions 1000

# 3. If delay > 30 seconds, enable enhanced fan-out for dedicated throughput
aws kinesis register-stream-consumer \
  --stream-arn arn:aws:kinesis:us-east-1:599626781403:stream/fantasy-sports-realtime-ingest \
  --consumer-name blitz-emergency-consumer

# 4. Monitor backlog clearing
watch -n 5 'aws cloudwatch get-metric-statistics \
  --namespace AWS/Kinesis \
  --metric-name IncomingRecords \
  --dimensions Name=StreamName,Value=fantasy-sports-realtime-ingest \
  --statistics Sum --period 60 --start-time $(date -d -5minutes +%Y-%m-%dT%H:%M:%SZ)'
```

---

### Scenario: Cloudflare Worker Cold Start

**Impact:** Initial WebSocket connections delayed 2-5 seconds, KV cache miss

**Detection:**

```bash
# Check Worker CPU time (cold starts show higher initial values)
wrangler tail --format=json | jq 'select(.cpuTime > 50)'

# Monitor KV cache hit rate
# (Check Cloudflare analytics dashboard)
```

**Response:**

```bash
# 1. Implement warming ping (automated via cron)
curl -s https://blitz-edge-observer.kindsonegbule15.workers.dev/health > /dev/null

# 2. If persistent cold starts, deploy to additional regions
# Update wrangler.toml with additional routes:
# routes = [
#   { pattern = "api-us.blitz-obs.com/*", zone_id = "..." },
#   { pattern = "api-eu.blitz-obs.com/*", zone_id = "..." }
# ]

# 3. Verify KV namespace health
wrangler kv:namespace list

# 4. Emergency: Switch to backup Worker deployment
wrangler deploy --env staging  # Deploy staging as emergency fallback
```

**Prevention:**

- Schedule warming requests every 5 minutes during game hours
- Use Durable Objects hibernation API for session persistence
- Deploy to multiple edge locations

---

### Scenario: EKS Capacity Exhausted

**Impact:** Lambda functions unable to scale, increased processing latency

**Response:**

```bash
# Emergency scale-up
aws eks update-nodegroup-config \
    --cluster-name blitz-edge-cluster \
    --nodegroup-name system \
    --scaling-config minSize=5,maxSize=20,desiredSize=10

# Verify node provisioning
kubectl get nodes -w

# If nodes stuck in NotReady, restart CNI
echo "Restarting AWS CNI..."
kubectl delete pod -n kube-system -l k8s-app=aws-node

# Force Karpenter to provision emergency nodes
kubectl apply -f - <<EOF
apiVersion: karpenter.sh/v1beta1
kind: NodePool
metadata:
  name: emergency
spec:
  template:
    spec:
      requirements:
        - key: karpenter.k8s.aws/instance-category
          operator: In
          values: [c, m]
        - key: karpenter.sh/capacity-type
          operator: In
          values: [spot, on-demand]
EOF
```

---

### Scenario: Kinesis Throttling

**Response:**

```bash
# Scale shards immediately
aws kinesis update-shard-count \
    --stream-name fantasy-sports-realtime-ingest \
    --target-shard-count 20 \
    --scaling-type UNIFORM_SCALING

# Monitor scaling progress
aws kinesis describe-stream --stream-name fantasy-sports-realtime-ingest --query 'StreamDescription.StreamStatus'
```

---

## Blue-Green Deployment Strategy

### Pre-Game Deployment Safety

```bash
# Deploy to Green (Staging) environment first
make deploy-backend  # Deploys to staging via Terraform workspace

# Run smoke tests against Green
./scripts/smoke_tests.sh --env staging

# Promote to Blue (Production) only after tests pass
terraform workspace select production
terraform apply -auto-approve

# If issues detected, instant rollback
terraform apply -target=module.eks -var='cluster_version=previous'
```

### Rollback Procedures

```bash
# Terraform rollback to last known good state
cd terraform/eks
terraform state list
terraform apply -target=module.eks -var='cluster_version=1.27'

# Cloudflare Worker rollback
cd edge
wrangler rollback

# Database state (DynamoDB) - no rollback needed (event-driven)
# KV cache - manual cleanup if needed:
wrangler kv:bulk delete --namespace-id=$GAME_STATE_KV_ID --file=keys_to_delete.txt

# Redis cache flush (if corrupted)
redis-cli -u $REDIS_URL FLUSHDB
```

### Chaos Validation Checklist

Run this checklist at least once per release candidate to validate resilience assumptions:

1. Redis failover simulation: verify fallback path and latency delta are documented.
2. Kinesis shard pressure: verify iterator age recovery after shard scale-out.
3. Worker cold-start drill: verify reconnection behavior and stale-cache window.
4. Scaler lock contention: verify DynamoDB lock TTL expiry and lock-owner logging.
5. Lambda retry path: verify failed batches land in DLQ and alarms trigger.

Capture evidence for each drill in:

- `tests/load/TEST_RESULTS.md`
- CloudWatch alarm history screenshots
- Relevant log excerpts from `/aws/lambda/*`

### Rollback Verification (Post-Action)

After any rollback, complete all checks before declaring recovery:

1. `terraform plan` shows no unintended drift for critical modules.
2. WebSocket `/health` endpoint returns success and active sessions recover.
3. Kinesis iterator age drops back to baseline range.
4. No active `ScalingErrors` alarms for 15 minutes.
5. Incident timeline and final root cause are appended to release notes.

---

## Cost Monitoring

### Daily Cost Check

```bash
# CloudWatch Logs cost
aws ce get-cost-and-usage \
    --time-period Start=$(date -d yesterday +%Y-%m-%d),End=$(date +%Y-%m-%d) \
    --granularity DAILY \
    --metrics BlendedCost
```

### Cost Thresholds

| Service         | Threshold | Action               |
| --------------- | --------- | -------------------- |
| CloudWatch Logs | $100/day  | Review FinOps filter |
| Kinesis         | $200/day  | Reduce retention     |
| Lambda          | $150/day  | Optimize settings    |
| EKS             | $500/day  | Review utilization   |

---

## Post-Game Cleanup

- Verify 'pause' pods auto-deleted by scaler
- Monitor S3 log archival for 93% savings
- Review CloudWatch dashboard for anomalies
- Update schedule.json for next week's games

---

## Auth, Replay, and Alerting Operations

### WebSocket Auth Validation Checks

```bash
# Verify auth secrets and rollout controls are present
cd edge
wrangler secret list
```

Operational notes:

- `REQUIRE_JWT_AUTH=true` enforces Bearer JWT validation on `/realtime`.
- League scope is enforced against the JWT `leagues` claim when present.
- Optional strict checks: `JWT_ISSUER`, `JWT_AUDIENCE`.

### Replay / Reconnect Behavior

- Clients reconnect with `since_ts=<last_server_timestamp>`.
- Durable Object replays buffered delta events newer than `since_ts` when available.
- If replay history is exhausted, clients still receive KV-backed `initial_state`.

### Alert Routing Setup

Configure one or both alert channels in Delta Processor Lambda environment:

```bash
ALERTS_SNS_TOPIC_ARN=arn:aws:sns:us-east-1:123456789012:blitz-edge-alerts
PAGERDUTY_WEBHOOK_URL=https://events.pagerduty.com/integration/...
```

Current high-priority alert triggers:

- Edge push circuit breaker opening
- Redis unavailable for delta computation
- Malformed record spikes

---

_Version 1.1.0 | Maintained by Platform Engineering_

