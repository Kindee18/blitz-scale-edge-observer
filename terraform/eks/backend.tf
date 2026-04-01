terraform {
  backend "s3" {
    bucket         = "blitz-terraform-state-prod"
    key            = "eks/terraform.tfstate"
    region         = "us-west-2"
    dynamodb_table = "blitz-terraform-locks"
    encrypt        = true
  }
}
