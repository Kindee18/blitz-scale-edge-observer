resource "aws_kms_key" "dynamodb_key" {
  description             = "KMS key for DynamoDB encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "dynamodb_key_alias" {
  name          = "alias/blitz-dynamodb-key"
  target_key_id = aws_kms_key.dynamodb_key.key_id
}

resource "aws_dynamodb_table" "scaling_locks" {
  name           = "blitz-edge-scaling-locks"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.dynamodb_key.arn
  }

  tags = {
    Environment = "Production"
    System      = "Blitz-Scale-Edge-Observer"
  }
}

resource "aws_dynamodb_table" "game_state_versions" {
  name           = "blitz-game-state-versions"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "GameID"
  range_key      = "Version"

  attribute {
    name = "GameID"
    type = "S"
  }

  attribute {
    name = "Version"
    type = "N"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.dynamodb_key.arn
  }

  tags = {
    Environment = "Production"
  }
}
