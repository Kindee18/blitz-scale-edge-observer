variable "aws_region" {
  description = "Region to deploy Kinesis/Lambda into"
  type        = string
  default     = "us-east-1"
}

resource "aws_kms_key" "blitz_key" {
  description             = "KMS key for Blitz-Scale Edge Observer infrastructure"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "blitz_key_alias" {
  name          = "alias/blitz-scale-key"
  target_key_id = aws_kms_key.blitz_key.key_id
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

data "aws_caller_identity" "current" {}

data "aws_secretsmanager_secret" "edge_token" {
  name = "blitz-edge-webhook-token"
}

resource "aws_kinesis_stream" "fantasy_sports_stream" {
  name             = "fantasy-sports-realtime-ingest"
  shard_count      = 10
  retention_period = 24

  encryption_type = "KMS"
  kms_key_id      = aws_kms_key.blitz_key.arn

  shard_level_metrics = [
    "IncomingBytes",
    "OutgoingBytes",
  ]

  tags = {
    Environment = "Production"
    System      = "Blitz-Scale-Edge-Observer"
  }
}

resource "aws_sqs_queue" "delta_processor_dlq" {
  name              = "blitz-delta-processor-dlq"
  kms_master_key_id = aws_kms_key.blitz_key.arn
}

resource "aws_iam_role" "lambda_kinesis_role" {
  name        = "lambda_kinesis_delta_processor"
  description = "Role for Lambda to process Kinesis streams and update Redis/DynamoDB"
  force_detach_policies = true

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

resource "aws_iam_role_policy" "lambda_scoped_access" {
  name        = "blitz-lambda-scoped-access"
  role        = aws_iam_role.lambda_kinesis_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Effect   = "Allow"
        Resource = [data.aws_secretsmanager_secret.edge_token.arn]
      },
      {
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem"
        ]
        Effect   = "Allow"
        Resource = ["arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/blitz-game-state-*"]
      }
    ]
  })
}

# The Lambda function for delta processing
resource "aws_lambda_function" "delta_processor" {
  function_name = "fantasy-data-delta-processor"
  role          = aws_iam_role.lambda_kinesis_role.arn
  handler       = "delta_processor_lambda.lambda_handler"
  runtime       = "python3.11"
  timeout       = 15

  tracing_config {
    mode = "Active"
  }

  # Dummy zip since the code is built via CI/CD
  filename         = "dummy.zip"
  source_code_hash = filebase64sha256("dummy.zip")

  environment {
    variables = {
      REDIS_URL             = "redis://blitz-cache.redis.amazonaws.com:6379"
      EDGE_WEBHOOK_URL      = "https://api.blitz-obs.com/webhook/update"
      WEBHOOK_SECRET_NAME   = "blitz-edge-webhook-token"
    }
  }
}

resource "aws_lambda_event_source_mapping" "kinesis_trigger" {
  event_source_arn  = aws_kinesis_stream.fantasy_sports_stream.arn
  function_name     = aws_lambda_function.delta_processor.arn
  starting_position = "LATEST"
  batch_size        = 100
  maximum_retry_attempts = 2
}
