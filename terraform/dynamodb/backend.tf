terraform {
  backend "s3" {
    bucket  = "blitz-terraform-state-599626781403"
    key     = "terraform/dynamodb/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
}