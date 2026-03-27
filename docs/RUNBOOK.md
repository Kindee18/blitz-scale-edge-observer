# Operational Runbook: NFL Sunday Traffic

## Pre-Game Checklist (T-30 mins)
1. Verify `scheduled_scaler_lambda` ran successfully.
2. Check EKS Node count (Should see Karpenter provisioning 'pause' pods).
3. Verify Redis CPU utilization is < 20%.

## Incident: High Delta Latency (> 200ms)
1. **Check**: Lambda Duration in CloudWatch.
2. **Action**: If Lambda is throttling, increase Kinesis Shard count via Terraform.
3. **Check**: Redis connection pool errors.

## Incident: Edge Webhook 429s or 503s
1. **Action**: Check Cloudflare Worker CPU/Duration limits.
2. **Action**: Verify `WEBHOOK_SECRET_TOKEN` hasn't expired or rotated incorrectly.

## Post-Game Cleanup
- Ensure 'pause' pods are deleted (Automated by `predictive_scaling.py`).
- Monitor S3 log archival for 93% filtering savings.
