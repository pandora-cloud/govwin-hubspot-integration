terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.45"
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

  # Federal compliance posture: every AWS API call from Terraform itself
  # resolves to a FIPS 140-validated TLS endpoint. NIST 800-53 SC-13,
  # CMMC L2 SC.L2-3.13.11. The Lambdas enforce the same via
  # AWS_USE_FIPS_ENDPOINT=true on each function (see modules/lambda/main.tf
  # and modules/ace/lambda.tf).
  use_fips_endpoint = true

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
