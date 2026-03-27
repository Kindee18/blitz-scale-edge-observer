# Blitz-Scale Edge Observer: Architecture Blueprint

## Overview
A multi-region, 100x spike-optimized data pipeline for real-time fantasy data delivery.

## Component Stack
1. **Ingest**: Amazon Kinesis (On-Demand Mode for auto-scaling).
2. **Compute**: AWS EKS with Karpenter (Predictive Scaling via 'Pause' pods).
3. **Streaming**: AWS Lambda (Delta Processing) + ElastiCache Redis (Global State).
4. **Edge**: Cloudflare Workers + Durable Objects (Real-Time WebSocket Broadcasting).
5. **Persistence**: DynamoDB (State Versioning) + S3 (Log Archival).

## Data Flow
`Source` -> `Kinesis` -> `Lambda (Delta Processor)` -> `Cloudflare (Edge Webhook)` -> `Durable Object` -> `WebSocket Client`

## Security
- OIDC for GitHub Actions -> AWS.
- AWS Secrets Manager for Edge Tokens.
- Cloudflare WAF + Rate Limiting.
- VPC Private Subnets for EKS & Redis.
