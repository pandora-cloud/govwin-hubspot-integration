terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Provider configuration. Day-N applies should assume the deployer role
# created by terraform/bootstrap (set deployer_role_arn in terraform.tfvars).
# When deployer_role_arn is empty (e.g. running from the bootstrap phase
# itself, or for local development with admin credentials), the provider
# falls back to the credentials in the configured AWS profile / env vars.
provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  dynamic "assume_role" {
    for_each = var.deployer_role_arn == "" ? [] : [var.deployer_role_arn]
    content {
      role_arn     = assume_role.value
      session_name = "terraform-${var.project_name}-${var.environment}"
    }
  }

  default_tags {
    tags = merge(
      {
        Project     = var.project_name
        Environment = var.environment
        ManagedBy   = "terraform"
      },
      var.tags
    )
  }
}
