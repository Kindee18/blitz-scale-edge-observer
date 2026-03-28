# Blitz-Scale Edge Observer - Operational Runbook

## Table of Contents
1. [Overview](#overview)
2. [Deployment Procedures](#deployment-procedures)
3. [Common Operations](#common-operations)
4. [Troubleshooting](#troubleshooting)
5. [Failure Scenarios](#failure-scenarios)
6. [Cost Monitoring](#cost-monitoring)
7. [Security & Compliance](#security--compliance)

---

## Overview

This runbook covers operational procedures for the Blitz-Scale Edge Observer infrastructure, designed to handle real-time fantasy sports scoring updates for FantasyPros Game Day.

**Key Components:**
- **Predictive Scaler:** EKS pre-warming for NFL Sunday spikes
- **Delta Processor:** Kinesis → Lambda → Fantasy points calculation
- **Edge Worker:** Cloudflare WebSocket broadcasting
- **FinOps Filter:** Log cost optimization (93% reduction)

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

### Scenario: EKS Capacity Exhausted

```bash
# Emergency scale-up
aws eks update-nodegroup-config \
    --cluster-name blitz-edge-cluster \
    --nodegroup-name system \
    --scaling-config minSize=5,maxSize=20,desiredSize=10
```

### Scenario: Kinesis Throttling

```bash
# Scale shards
aws kinesis update-shard-count \
    --stream-name blitz-data-stream \
    --target-shard-count 20 \
    --scaling-type UNIFORM_SCALING
```

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

| Service | Threshold | Action |
|---------|-----------|--------|
| CloudWatch Logs | $100/day | Review FinOps filter |
| Kinesis | $200/day | Reduce retention |
| Lambda | $150/day | Optimize settings |
| EKS | $500/day | Review utilization |

---

## Post-Game Cleanup

- Verify 'pause' pods auto-deleted by scaler
- Monitor S3 log archival for 93% savings
- Review CloudWatch dashboard for anomalies
- Update schedule.json for next week's games

---

*Version 1.1.0 | Maintained by Platform Engineering*
