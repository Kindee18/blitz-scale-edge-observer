resource "aws_dynamodb_table" "scaling_locks" {
  name           = "blitz-edge-scaling-locks"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  server_side_encryption {
    enabled = true
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
    enabled = true
  }

  tags = {
    Environment = "Production"
  }
}
