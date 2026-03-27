resource "aws_secretsmanager_secret" "edge_token" {
  name        = "blitz-edge-webhook-token"
  description = "Shared secret for Lambda to Worker authentication"
  recovery_window_in_days = 0
  kms_key_id = aws_kms_key.blitz_root_key.arn
}

resource "aws_secretsmanager_secret_version" "edge_token_v1" {
  secret_id     = aws_secretsmanager_secret.edge_token.id
  secret_string = "secure-edge-token-12345"
}

resource "aws_secretsmanager_secret" "redis_auth" {
  name        = "blitz-redis-auth"
  description = "Authentication for ElastiCache Redis"
  recovery_window_in_days = 0 
  kms_key_id = aws_kms_key.blitz_root_key.arn
}
