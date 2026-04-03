variable "aws_region" {
  description = "AWS region for shared observability and cost controls"
  type        = string
  default     = "us-east-1"
}

variable "alert_email" {
  description = "Email address for operational alerts"
  type        = string
  default     = "kindson002@gmail.com"
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Environment = "Production"
      Project     = "Blitz-Scale-Edge-Observer"
      ManagedBy   = "Terraform"
    }
  }
}

resource "aws_budgets_budget" "blitz_cost_limit" {
  name              = "blitz-edge-monthly-budget"
  budget_type       = "COST"
  limit_amount      = "2000"
  limit_unit        = "USD"
  time_period_start = "2026-03-01_00:00"
  time_unit         = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["admin@blitz-obs.com"]
  }
}

resource "aws_sns_topic" "ops_alerts" {
  name = "blitz-edge-ops-alerts"
}

resource "aws_sns_topic_subscription" "ops_alerts_email" {
  topic_arn = aws_sns_topic.ops_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors_high" {
  alarm_name          = "blitz-delta-processor-errors-high"
  alarm_description   = "Delta processor Lambda has elevated errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = "fantasy-data-delta-processor"
  }

  alarm_actions = [aws_sns_topic.ops_alerts.arn]
  ok_actions    = [aws_sns_topic.ops_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "lambda_duration_p95_high" {
  alarm_name          = "blitz-delta-processor-duration-p95-high"
  alarm_description   = "Delta processor Lambda p95 duration is high"
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  extended_statistic  = "p95"
  period              = 60
  evaluation_periods  = 5
  threshold           = 12000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = "fantasy-data-delta-processor"
  }

  alarm_actions = [aws_sns_topic.ops_alerts.arn]
  ok_actions    = [aws_sns_topic.ops_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "kinesis_iterator_age_high" {
  alarm_name          = "blitz-kinesis-iterator-age-high"
  alarm_description   = "Kinesis iterator age indicates consumer lag"
  namespace           = "AWS/Kinesis"
  metric_name         = "GetRecords.IteratorAgeMilliseconds"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 60000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    StreamName = "fantasy-sports-realtime-ingest"
  }

  alarm_actions = [aws_sns_topic.ops_alerts.arn]
  ok_actions    = [aws_sns_topic.ops_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "redis_engine_cpu_high" {
  alarm_name          = "blitz-redis-engine-cpu-high"
  alarm_description   = "Redis engine CPU is high"
  namespace           = "AWS/ElastiCache"
  metric_name         = "EngineCPUUtilization"
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 5
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    ReplicationGroupId = "blitz-edge-redis"
  }

  alarm_actions = [aws_sns_topic.ops_alerts.arn]
  ok_actions    = [aws_sns_topic.ops_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "redis_connections_high" {
  alarm_name          = "blitz-redis-connections-high"
  alarm_description   = "Redis current connections are high"
  namespace           = "AWS/ElastiCache"
  metric_name         = "CurrConnections"
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 5
  threshold           = 800
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    ReplicationGroupId = "blitz-edge-redis"
  }

  alarm_actions = [aws_sns_topic.ops_alerts.arn]
  ok_actions    = [aws_sns_topic.ops_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "edge_push_failure_batches" {
  alarm_name          = "blitz-edge-push-failure-batches"
  alarm_description   = "Delta processor observed edge push failures (including webhook 401 spikes)"
  namespace           = "BlitzScale/Edge"
  metric_name         = "EdgePushFailureBatches"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.ops_alerts.arn]
  ok_actions    = [aws_sns_topic.ops_alerts.arn]
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "Blitz-Scale-Observer-Ops"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["BlitzScale/Edge", "DeltasProduced"]
          ]
          period = 60
          stat   = "Sum"
          region = "us-east-1"
          title  = "Total Deltas Produced (1m)"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", "fantasy-data-delta-processor"]
          ]
          period = 60
          stat   = "Average"
          region = "us-east-1"
          title  = "Lambda Processing Latency"
        }
      }
    ]
  })
}
