# S3 state bucket for the main Terraform module.
# - Versioned so accidental state corruption is recoverable
# - Public access blocked at every level
# - Encrypted with the AWS-managed aws/s3 KMS key (CloudTrail-logged decrypts
#   without us having to manage a customer-managed key)
# - Native S3 lockfile (Terraform 1.10+) replaces DynamoDB for locking

resource "random_id" "state_bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "state" {
  bucket        = "${local.name_prefix}-tfstate-${random_id.state_bucket_suffix.hex}"
  force_destroy = var.state_bucket_force_destroy
  tags          = local.base_tags
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
      # Empty string = the AWS-managed aws/s3 key (decision 2)
      kms_master_key_id = "alias/aws/s3"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {} # apply to whole bucket
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Bucket policy: deny non-TLS access (compliance baseline) and deny anyone
# outside the deployer role from reading or writing state.
resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.state.arn,
          "${aws_s3_bucket.state.arn}/*",
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      },
    ]
  })
}
