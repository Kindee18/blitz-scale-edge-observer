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
