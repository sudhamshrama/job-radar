# The Terraform state backend for every other configuration in this repo.
#
# S3 bucket names are globally unique across all AWS accounts, so the account ID
# is appended. State files are a few KB, well inside the free tier.

resource "aws_s3_bucket" "tfstate" {
  bucket = "job-radar-tfstate-${var.account_id}"

  # Losing this bucket means losing the record of every resource Terraform
  # manages. `terraform destroy` in the app environments must never be able to
  # take it out. Removing this requires a deliberate code edit — see ADR 0002.
  lifecycle {
    prevent_destroy = true
  }
}

# Versioning is the actual recovery mechanism for state corruption: a bad apply
# or a truncated write can be rolled back to the previous object version.
resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled"
  }
}

# State files contain resource attributes in plaintext — ARNs, endpoints, and
# anything a resource exposes. In url-shortener, gitleaks caught Log Analytics
# shared keys sitting in a state backup. Encrypt at rest by default.
resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      # SSE-S3 (AES256), not SSE-KMS. A customer-managed KMS key costs ~$1/mo
      # and this account has a $0 budget. AES256 is free and still encrypts.
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Versioning keeps every historical state file forever by default. Harmless at
# this scale, but it is free-tier storage and old versions have no value after
# a few weeks. Expire them rather than letting them accumulate silently.
resource "aws_s3_bucket_lifecycle_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  # Explicit dependency: applying a lifecycle rule while versioning is still
  # being enabled can race.
  depends_on = [aws_s3_bucket_versioning.tfstate]

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
