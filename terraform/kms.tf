resource "aws_kms_key" "blitz_root_key" {
  description             = "KMS key for Blitz-Scale Edge Observer root infrastructure"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "blitz_root_key_alias" {
  name          = "alias/blitz-scale-root-key"
  target_key_id = aws_kms_key.blitz_root_key.key_id
}
