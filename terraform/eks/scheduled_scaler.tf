resource "aws_cloudwatch_event_rule" "scale_check_schedule" {
  name                = "blitz-predictive-scale-check"
  description         = "Triggers predictive scaling check every 15 minutes"
  schedule_expression = "rate(15 minutes)"
}

resource "aws_cloudwatch_event_target" "scale_check_target" {
  rule      = aws_cloudwatch_event_rule.scale_check_schedule.name
  target_id = "PredictiveScalerLambda"
  arn       = aws_lambda_function.scheduled_scaler.arn
}

resource "aws_lambda_permission" "allow_cloudwatch_to_call_scaler" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduled_scaler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.scale_check_schedule.arn
}

# The Placeholder for the Lambda itself (we would normally define this in a module)
resource "aws_lambda_function" "scheduled_scaler" {
  function_name = "blitz-edge-scheduled-scaler"
  role          = aws_iam_role.lambda_kinesis_role.arn # Reusing role for simplicity or creating new one
  handler       = "scheduled_scaler_lambda.lambda_handler"
  runtime       = "python3.11"
  timeout       = 30
  
  tracing_config {
    mode = "Active"
  }
  
  filename         = "dummy.zip"
  source_code_hash = filebase64sha256("dummy.zip")

  environment {
    variables = {
      EKS_CLUSTER_NAME   = "blitz-edge-cluster"
      SCHEDULE_S3_BUCKET = "blitz-edge-config"
    }
  }
}
