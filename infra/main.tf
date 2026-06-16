terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  backend "s3" {
    bucket = "prodrescue-tf-state"
    key    = "prod/terraform.tfstate"
    region = "us-east-1"
  }
}

provider "aws" {
  region = var.region
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name            = "prodrescue"
  cidr            = "10.0.0.0/16"
  azs             = ["${var.region}a", "${var.region}b"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = true
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = "prodrescue"
  cluster_version = "1.30"
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.private_subnets

  eks_managed_node_groups = {
    agents = {
      instance_types = ["t3.medium"]
      min_size       = 1
      max_size       = 5
      desired_size   = 2
    }
  }
}

resource "aws_db_parameter_group" "timescale" {
  name   = "timescaledb-pg15"
  family = "postgres15"

  parameter {
    name         = "shared_preload_libraries"
    value        = "timescaledb,pg_stat_statements"
    apply_method = "pending-reboot"
  }
}

resource "aws_db_instance" "postgres" {
  identifier           = "prodrescue-db"
  engine               = "postgres"
  engine_version       = "15.4"
  instance_class       = "db.t3.medium"
  allocated_storage    = 50
  storage_encrypted    = true
  username             = "prodrescue"
  password             = var.db_password
  parameter_group_name = aws_db_parameter_group.timescale.name
  skip_final_snapshot  = false
  db_subnet_group_name = aws_db_subnet_group.main.name
}

resource "aws_db_subnet_group" "main" {
  name       = "prodrescue-db-subnets"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id      = "prodrescue-redis"
  engine          = "redis"
  node_type       = "cache.t3.micro"
  num_cache_nodes = 1
}

resource "aws_ecr_repository" "prodrescue" {
  name                 = "prodrescue"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}
