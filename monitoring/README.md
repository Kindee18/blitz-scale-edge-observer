# CloudWatch Dashboard and Alarms for Blitz-Scale Edge Observer

This directory contains monitoring configurations for the infrastructure.

## Files

- `cloudwatch_dashboard.json` - CloudWatch dashboard definition
- `custom_metrics.py` - Helper for emitting consistent custom metrics
- `README.md` - This file

## Key Metrics

### Performance Metrics
- `DeltasProduced` - Number of deltas computed per batch
- `EdgePushLatency` - Time to push to Cloudflare edge
- `ScalingExecutionDuration` - Predictive scaler execution time
- `WebSocketLatency` - End-to-end latency for client updates

### Business Metrics
- `FantasyPointsDelta_*` - Fantasy points updates by scoring format
- `ConnectedClients` - Active WebSocket connections
- `BroadcastSuccessRate` - Successful message broadcasts

### Infrastructure Metrics
- `ScalingErrors` - Predictive scaler failures
- `ScalingLockContention` - DynamoDB lock conflicts
- `KinesisLag` - Consumer lag behind stream head

## Dashboard Access

The CloudWatch dashboard is deployed via Terraform. Access it:

```bash
aws cloudwatch get-dashboard --dashboard-name blitz-scale-edge-observer
```
