terraform {
  # 1.10+ is required for native S3 state locking (use_lockfile). Older
  # versions needed a separate DynamoDB table just to hold a lock row.
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      # Pin the major version. ">= 5.0" would silently accept a future 7.x
      # with breaking changes; the lock file pins the exact build.
      version = "~> 6.0"
    }
  }

  # Chicken-and-egg: this configuration CREATES the bucket below, so on the
  # first run there was no backend to write to and state was local. Once the
  # bucket existed, this block was added and the state migrated into it with
  # `terraform init -migrate-state`. Bootstrap now manages its own backend.
  # See docs/decisions/0002-terraform-state-backend-bootstrap.md
  backend "s3" {
    bucket       = "job-radar-tfstate-428625199448"
    key          = "bootstrap/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "job-radar"
      ManagedBy = "terraform"
      Component = "bootstrap"
    }
  }
}
