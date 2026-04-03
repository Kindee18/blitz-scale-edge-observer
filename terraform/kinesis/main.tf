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

variable "edge_webhook_url" {
  description = "Webhook endpoint for edge update pushes."
  type        = string
  default     = "https://blitz-edge-observer.kindsonegbule15.workers.dev/webhook/update"
}

variable "lambda_vpc_subnet_ids" {
  description = "Private subnet IDs for Lambda VPC networking."
  type        = list(string)
  default = [
    "subnet-061628e5efdba569e",
    "subnet-0267049c261b0a2bf",
    "subnet-015eee29733fd6a29",
  ]
}

variable "vpc_id" {
  description = "VPC ID where Lambda and Redis are provisioned."
  type        = string
  default     = "vpc-086f1dcd8b724c877"
}

variable "delta_processor_layer_arn" {
  description = "Prebuilt dependency layer ARN for the delta processor Lambda."
  type        = string
  default     = "arn:aws:lambda:us-east-1:599626781403:layer:fantasy-data-delta-deps:8"
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

locals {
  redis_url = "redis://${aws_elasticache_replication_group.blitz_edge_redis.primary_endpoint_address}:${aws_elasticache_replication_group.blitz_edge_redis.port}"
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
  name                  = "lambda_kinesis_delta_processor"
  description           = "Role for Lambda to process Kinesis streams and update Redis/DynamoDB"
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
  name = "blitz-lambda-scoped-access"
  role = aws_iam_role.lambda_kinesis_role.id

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
      },
      {
        Action = [
          "cloudwatch:PutMetricData"
        ]
        Effect   = "Allow"
        Resource = ["*"]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_vpc_access" {
  role       = aws_iam_role.lambda_kinesis_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_security_group" "lambda_redis_egress" {
  name        = "blitz-delta-lambda-redis-egress"
  description = "Lambda egress to Redis"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "redis_ingress" {
  name        = "blitz-redis-ingress"
  description = "Allow Redis from Lambda"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "redis_from_lambda" {
  security_group_id            = aws_security_group.redis_ingress.id
  referenced_security_group_id = aws_security_group.lambda_redis_egress.id
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
}

resource "aws_elasticache_subnet_group" "blitz_edge_redis" {
  name       = "blitz-edge-redis-subnet-group"
  subnet_ids = var.lambda_vpc_subnet_ids
}

resource "aws_elasticache_replication_group" "blitz_edge_redis" {
  replication_group_id       = "blitz-edge-redis"
  description                = "Blitz edge redis cache"
  engine                     = "redis"
  node_type                  = "cache.t4g.micro"
  num_node_groups            = 1
  replicas_per_node_group    = 0
  automatic_failover_enabled = false

  subnet_group_name  = aws_elasticache_subnet_group.blitz_edge_redis.name
  security_group_ids = [aws_security_group.redis_ingress.id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = false
  auto_minor_version_upgrade = true

  tags = {
    Project = "Blitz-Scale-Edge-Observer"
  }
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

  layers = [var.delta_processor_layer_arn]

  vpc_config {
    subnet_ids         = var.lambda_vpc_subnet_ids
    security_group_ids = [aws_security_group.lambda_redis_egress.id]
  }

  # Package current lambda source into a deployment zip during terraform apply.
  filename         = data.archive_file.delta_processor_dummy_zip.output_path
  source_code_hash = data.archive_file.delta_processor_dummy_zip.output_base64sha256

  environment {
    variables = {
      REDIS_URL           = local.redis_url
      EDGE_WEBHOOK_URL    = var.edge_webhook_url
      WEBHOOK_SECRET_NAME = "blitz-edge-webhook-token"
    }
  }
}

resource "aws_lambda_event_source_mapping" "kinesis_trigger" {
  count                  = var.deploy_delta_processor_lambda ? 1 : 0
  event_source_arn       = aws_kinesis_stream.fantasy_sports_stream.arn
  function_name          = aws_lambda_function.delta_processor[0].arn
  starting_position      = "LATEST"
  batch_size             = 100
  maximum_retry_attempts = 2

  # Avoid eventual-consistency races where mapping creation starts before role policy is attached.
  depends_on = [
    aws_iam_role_policy.lambda_scoped_access,
    aws_iam_role_policy_attachment.lambda_vpc_access,
  ]
}
