variable "aws_region" {
  description = "Region to deploy Kinesis/Lambda into"
  type        = string
  default     = "us-east-1"
}

variable "deploy_delta_processor_lambda" {
  description = "Whether to create the delta processor Lambda and event source mapping in this stack."
  type        = bool
  default     = true
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
        Resource = ["arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:blitz-edge-webhook-token*"]
      },
      {
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem"
        ]
        Effect   = "Allow"
        Resource = ["arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/blitz-game-state-*"]
      },
      {
        Action = [
          "kinesis:GetRecords",
          "kinesis:GetShardIterator",
          "kinesis:DescribeStream",
          "kinesis:DescribeStreamSummary",
          "kinesis:ListShards",
          "kinesis:ListStreams"
        ]
        Effect = "Allow"
        Resource = [
          aws_kinesis_stream.fantasy_sports_stream.arn
        ]
      },
      {
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Effect = "Allow"
        Resource = [
          "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/fantasy-data-delta-processor:*",
          "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/fantasy-data-delta-processor"
        ]
      }
    ]
  })
}

data "archive_file" "delta_processor_dummy_zip" {
  type        = "zip"
  output_path = "${path.module}/.generated-delta-processor.zip"

  source {
    content  = file("${path.module}/../../streaming/delta_processor_lambda.py")
    filename = "delta_processor_lambda.py"
  }

  source {
    content  = file("${path.module}/../../streaming/fantasy_scoring.py")
    filename = "fantasy_scoring.py"
  }

  source {
    content  = file("${path.module}/../../monitoring/custom_metrics.py")
    filename = "monitoring/custom_metrics.py"
  }

  source {
    content  = ""
    filename = "monitoring/__init__.py"
  }
}

resource "aws_lambda_layer_version" "delta_processor_dependencies" {
  layer_name          = "fantasy-data-delta-deps"
  filename            = data.archive_file.delta_processor_layer_zip.output_path
  source_code_hash    = data.archive_file.delta_processor_layer_zip.output_base64sha256
  compatible_runtimes = ["python3.11"]
}

data "archive_file" "delta_processor_layer_zip" {
  type        = "zip"
  source_dir  = path.module
  output_path = "${path.module}/lambda_layer.zip"

  excludes = [
    "*.tf",
    "*.tfvars",
    ".terraform.lock.hcl",
    ".terraform/*",
    ".terraform/**",
    "lambda_layer.zip",
    ".generated-delta-processor.zip"
  ]
}

# The Lambda function for delta processing
resource "aws_lambda_function" "delta_processor" {
  count         = var.deploy_delta_processor_lambda ? 1 : 0
  function_name = "fantasy-data-delta-processor"
  role          = aws_iam_role.lambda_kinesis_role.arn
  handler       = "delta_processor_lambda.lambda_handler"
  runtime       = "python3.11"
  timeout       = 15

  tracing_config {
    mode = "Active"
  }

  layers = [aws_lambda_layer_version.delta_processor_dependencies.arn]

  # Package current lambda source into a deployment zip during terraform apply.
  filename         = data.archive_file.delta_processor_dummy_zip.output_path
  source_code_hash = data.archive_file.delta_processor_dummy_zip.output_base64sha256

  environment {
    variables = {
      REDIS_URL             = "redis://blitz-cache.redis.amazonaws.com:6379"
      EDGE_WEBHOOK_URL      = "https://api.blitz-obs.com/webhook/update"
      WEBHOOK_SECRET_NAME   = "blitz-edge-webhook-token"
    }
  }
}

resource "aws_lambda_event_source_mapping" "kinesis_trigger" {
  count              = var.deploy_delta_processor_lambda ? 1 : 0
  event_source_arn  = aws_kinesis_stream.fantasy_sports_stream.arn
  function_name     = aws_lambda_function.delta_processor[0].arn
  starting_position = "LATEST"
  batch_size        = 100
  maximum_retry_attempts = 2

  # Avoid eventual-consistency races where mapping creation starts before role policy is attached.
  depends_on = [aws_iam_role_policy.lambda_scoped_access]
}
