resource "aws_secretsmanager_secret" "edge_token" {
  name        = "blitz-edge-webhook-token"
  description = "Shared secret for Lambda to Worker authentication"
  recovery_window_in_days = 0
  kms_key_id = aws_kms_key.blitz_root_key.arn
}

resource "aws_secretsmanager_secret_version" "edge_token_v1" {
  secret_id     = aws_secretsmanager_secret.edge_token.id
  secret_string = var.edge_webhook_secret_token
}

variable "edge_webhook_secret_token" {
  description = "Webhook secret used between edge and processor; provide via tfvars or env var TF_VAR_edge_webhook_secret_token."
  type        = string
  sensitive   = true
  default     = "REPLACE_WITH_SECURE_TOKEN"
}

resource "aws_secretsmanager_secret" "redis_auth" {
  name        = "blitz-redis-auth"
  description = "Authentication for ElastiCache Redis"
  recovery_window_in_days = 0 
  kms_key_id = aws_kms_key.blitz_root_key.arn
}
