data "aws_availability_zones" "available" {}
data "aws_caller_identity" "current" {}

locals {
  name   = "blitz-edge-cluster"
  vpc_cidr = "10.0.0.0/16"
  azs      = slice(data.aws_availability_zones.available.names, 0, 3)
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = local.name
  cidr = local.vpc_cidr

  azs             = local.azs
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets  = ["10.0.4.0/24", "10.0.5.0/24", "10.0.6.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = false
  enable_dns_hostnames = true
  enable_dns_support   = true

  # Tags required by Karpenter
  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = 1
    "karpenter.sh/discovery" = local.name
  }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 19.16"

  cluster_name    = local.name
  cluster_version = "1.28"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access = true
  cluster_endpoint_public_access_cidrs = ["0.0.0.0/0"] # Low-severity finding, but explicit is better or restriction needed
  
  cluster_enabled_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
  create_cloudwatch_log_group = true
  cluster_log_retention_in_days = 90

  # We use Karpenter primarily, but need a minimal managed node group for system pods
  eks_managed_node_groups = {
    system = {
      instance_types = ["m5.large"]
      min_size     = 2
      max_size     = 5
      desired_size = 2
    }
  }

  manage_aws_auth_configmap = true
}
