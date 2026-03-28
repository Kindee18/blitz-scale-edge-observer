# Dead Letter Queue (DLQ) Configuration for Kinesis Lambda

This directory contains DLQ configuration for handling failed Kinesis records.

## Architecture

When the Delta Processor Lambda fails to process Kinesis records:
1. Records are sent to SQS Dead Letter Queue after 3 retry attempts
2. DLQ holds failed records for analysis and replay
3. CloudWatch alarm notifies on DLQ depth

## Terraform Resources

See `terraform/kinesis/main.tf` for:
- `aws_sqs_queue.kinesis_dlq` - DLQ for failed records
- `aws_lambda_event_source_mapping` - Kinesis trigger with DLQ config
- `aws_cloudwatch_metric_alarm.dlq_depth` - Alert on queue depth

## Manual Replay

To replay failed records:

```bash
# Purge and analyze DLQ
aws sqs purge-queue --queue-url https://sqs.us-east-1.amazonaws.com/123456789/blitz-kinesis-dlq

# Or move to replay queue for reprocessing
aws sqs send-message --queue-url https://sqs.us-east-1.amazonaws.com/123456789/blitz-replay-queue \
  --message-body file://failed_record.json
```

## Monitoring

- DLQ Depth Alarm: Triggers at > 100 messages
- Notification: SNS topic `blitz-dlq-alerts`
