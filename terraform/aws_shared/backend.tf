terraform {
  backend "s3" {
    bucket  = "blitz-terraform-state-599626781403"
    key     = "terraform/aws_shared/terraform.tfstate"
    region  = "us-west-2"
    encrypt = true
  }
}
