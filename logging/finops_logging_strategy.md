# FinOps Logging Optimization

## Problem Statement
During an extreme scaling event (e.g., Sunday NFL spikes), microservices generate billions of log lines per hour. Standard practices usually sink all logs to CloudWatch or Datadog, incurring massive ingestion and storage costs, often exceeding the cost of the compute itself.

## Implementation Architecture
1. **CloudWatch Log Subscription**: 
   - EKS and Kinesis Lambda logs are sent to local CloudWatch log groups with a 1-day retention limit (to minimize storage cost).
   - A CloudWatch Subscription Filter streams these logs immediately to the `log_filter_lambda`.
   
2. **Lambda Filter (The Log Processor)**:
   - Evaluates incoming payloads, unzips them, and analyzes each line.
   - **Dropped Data**: Heartbeats, deep debug trails, and redundant metrics.
   - **Retained Data**: Exceptions, `ERROR` level trace records, and critical domain events (`gameplay_event`).

3. **S3 Cold Storage (Data Lake)**:
   - Retained data is batched out to Amazon S3 Standard-IA (Infrequent Access) or Glacier. 
   - S3 costs ~$0.023/GB compared to Datadog's ~$0.10/GB or CloudWatch's ~$0.50/GB ingested.

## Estimated Cost Reduction
| Metric | Standard Architecture | Optimized Architecture |
|--------|-----------------------|------------------------|
| Ingestion Vol. | 10 TB / month | 10 TB -> 0.5 TB (after filter) |
| CloudWatch Cost| $5,000 / month | $250 / month |
| S3 Storage | $0 | $11.50 / month (0.5 TB) |
| Lambda Cost | $0 | ~$50 / month |
| **Total Cost** | **$5,000 / mo** | **$311.50 / mo (~93% reduction)** |

By intelligently filtering logs before they hit expensive long-term indexing solutions, we ensure observability over anomalous behavior while ruthlessly minimizing the ingestion tax of "clean" operations.
