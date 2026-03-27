# Cost Model & FinOps Strategy

## Projected Savings
- **Logging**: 93% reduction ($15k/mo -> $1k/mo) via intelligent filtering.
- **Compute**: 40% reduction via Karpenter Spot Instance orchestration.

## Estimated Monthly Burn
| Component | Unit | Cost (Est) | Note |
|-----------|------|------------|------|
| EKS Control Plane | 1 | $73 | Fixed |
| EKS Nodes (Spot) | ~50 | $800 | Dynamic based on Sunday spikes |
| Kinesis (On-Demand)| - | $150 | - |
| Cloudflare Workers | - | $50 | Paid tier for Durable Objects |
| Redis (ElastiCache)| 1 (cache.t4g.small)| $30 | - |

## Optimization Lever
Increase the log-filtering aggressiveness in `log_filter_lambda.py` if S3 storage costs exceed budget.
