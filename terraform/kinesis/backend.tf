terraform {
  backend "s3" {
    bucket  = "blitz-terraform-state-599626781403"
    key     = "terraform/kinesis/terraform.tfstate"
    region  = "us-west-2"
    encrypt = true
  }
}