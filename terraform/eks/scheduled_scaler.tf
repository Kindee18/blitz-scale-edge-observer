# DynamoDB Table for Idempotency Locking
resource "aws_dynamodb_table" "scaling_locks" {
  name         = "blitz-scaling-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "lock_id"

  attribute {
    name = "lock_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  ttl {
    attribute_name = "expiration_time"
    enabled        = true
  }

  tags = {
    Name        = "blitz-scaling-locks"
    Environment = "Production"
    Purpose     = "Predictive Scaling Idempotency"
  }
}

# S3 Bucket for schedule storage (if not already created)
resource "aws_s3_bucket" "config_bucket" {
  bucket = "blitz-edge-config-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "config_bucket_versioning" {
  bucket = aws_s3_bucket.config_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

# IAM Role for Scheduled Scaler Lambda
resource "aws_iam_role" "scheduled_scaler_role" {
  name = "blitz-scheduled-scaler-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

# IAM Policy for Lambda permissions
resource "aws_iam_policy" "scheduled_scaler_policy" {
  name        = "blitz-scheduled-scaler-policy"
  description = "Permissions for predictive scaling Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem"
        ]
        Resource = aws_dynamodb_table.scaling_locks.arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.config_bucket.arn,
          "${aws_s3_bucket.config_bucket.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "eks:DescribeCluster"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "scheduled_scaler_attach" {
  role       = aws_iam_role.scheduled_scaler_role.name
  policy_arn = aws_iam_policy.scheduled_scaler_policy.arn
}

# CloudWatch EventBridge Rule for scheduling
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

# Lambda Layer for Python dependencies (kubernetes, boto3, etc.)
resource "aws_lambda_layer_version" "scaling_dependencies" {
  layer_name = "blitz-scaling-deps"
  
  filename         = "${path.module}/lambda_layer.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda_layer.zip")
  
  compatible_runtimes = ["python3.11"]
  
  description = "Dependencies for predictive scaling Lambda (kubernetes, boto3)"
}

# Lambda Function
resource "aws_lambda_function" "scheduled_scaler" {
  function_name = "blitz-edge-scheduled-scaler"
  role          = aws_iam_role.scheduled_scaler_role.arn
  handler       = "scheduled_scaler_lambda.lambda_handler"
  runtime       = "python3.11"
  timeout       = 60
  memory_size   = 512

  filename         = "${path.module}/scheduled_scaler.zip"
  source_code_hash = data.archive_file.scheduled_scaler_zip.output_base64sha256

  layers = [aws_lambda_layer_version.scaling_dependencies.arn]

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = {
      EKS_CLUSTER_NAME    = module.eks.cluster_name
      SCHEDULE_S3_BUCKET  = aws_s3_bucket.config_bucket.id
      SCHEDULE_S3_KEY     = "schedule.json"
      DYNAMODB_LOCK_TABLE = aws_dynamodb_table.scaling_locks.name
      LOCK_TTL_SECONDS    = "300"
      LEAD_TIME_MINUTES   = "45"
      DRY_RUN_MODE        = "false"
    }
  }

  vpc_config {
    subnet_ids         = module.vpc.private_subnets
    security_group_ids = length(aws_security_group.lambda_egress) > 0 ? [aws_security_group.lambda_egress[0].id] : []
  }

  depends_on = [aws_iam_role_policy_attachment.scheduled_scaler_attach]
}

# Security Group for Lambda VPC access
data "aws_security_group" "lambda_egress" {
  name = "${local.name}-lambda-egress"
  
  # Create if doesn't exist
  count = 0
}

resource "aws_security_group" "lambda_egress" {
  count = length(data.aws_security_group.lambda_egress) == 0 ? 1 : 0
  
  name        = "${local.name}-lambda-egress"
  description = "Allow Lambda egress to EKS and AWS services"
  vpc_id      = module.vpc.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name}-lambda-egress"
  }
}

# Archive Lambda code
data "archive_file" "scheduled_scaler_zip" {
  type        = "zip"
  output_path = "${path.module}/scheduled_scaler.zip"

  source {
    content  = file("${path.module}/../../scaling/scheduled_scaler_lambda.py")
    filename = "scheduled_scaler_lambda.py"
  }

  source {
    content  = file("${path.module}/../../scaling/predictive_scaling.py")
    filename = "predictive_scaling.py"
  }

  source {
    content  = file("${path.module}/../../scaling/eks_auth.py")
    filename = "eks_auth.py"
  }
}

# CloudWatch Alarms for Scaling Operations
resource "aws_cloudwatch_metric_alarm" "scaling_failures" {
  alarm_name          = "blitz-scaling-failures"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ScalingErrors"
  namespace           = "BlitzScale/PredictiveScaling"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Alert when predictive scaling encounters errors"
  alarm_actions       = []  # Add SNS topic ARN here for notifications

  dimensions = {
    ErrorType = "All"
  }
}

resource "aws_cloudwatch_metric_alarm" "scaling_duration_high" {
  alarm_name          = "blitz-scaling-duration-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ScalingExecutionDuration"
  namespace           = "BlitzScale/PredictiveScaling"
  period              = 300
  statistic           = "Average"
  threshold           = 45
  alarm_description   = "Alert when scaling execution takes longer than expected"
}
