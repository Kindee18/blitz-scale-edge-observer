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
            [ "BlitzScale/Edge", "DeltasProduced" ]
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
            [ "AWS/Lambda", "Duration", "FunctionName", "blitz-edge-delta-processor" ]
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
