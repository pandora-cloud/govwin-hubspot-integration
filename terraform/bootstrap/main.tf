# Bootstrap module: one-time setup that prepares an AWS account for
# deploying the GovWin to AWS Partner Central integration with proper
# least-privilege IAM. Run this once per environment with bootstrap-operator
# credentials, then delete those credentials.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.43"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  current_region = data.aws_region.current.name
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  base_tags = merge(
    {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform-bootstrap"
    },
    var.tags,
  )
}
