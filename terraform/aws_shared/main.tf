variable "aws_region" {
  description = "AWS region for shared observability and cost controls"
  type        = string
  default     = "us-east-1"
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
