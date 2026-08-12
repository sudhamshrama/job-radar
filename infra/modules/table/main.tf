variable "name" { type = string }
variable "tags" {
  type    = map(string)
  default = {}
}

# PROVISIONED, not PAY_PER_REQUEST.
#
# This is the single most important cost decision in the project. DynamoDB's
# always-free allowance is 25 RCU + 25 WCU on PROVISIONED capacity. On-demand
# billing has no equivalent always-free tier — it bills per request from the
# first one. Switching this to PAY_PER_REQUEST "for convenience" is how a $0
# serverless project starts costing money.
#
# 5/5 is deliberate: it leaves headroom under the 25/25 account-wide limit for
# the GSI, which consumes its own separate capacity.
resource "aws_dynamodb_table" "this" {
  # checkov:skip=CKV_AWS_28:Point-in-time recovery is billed per GB of backup.
  # This table is a 90-day cache of public job postings, fully reproducible by
  # re-running ingest. Paying to back up regenerable data is the wrong trade at
  # a $0 budget. PITR would be correct for data that cannot be recreated.
  # checkov:skip=CKV_AWS_119:A customer-managed CMK is ~$1/month. The table is
  # encrypted at rest with an AWS-owned key at no charge. Same reasoning as the
  # Terraform state bucket in ADR 0002. The data is public job listings.
  name         = var.name
  billing_mode = "PROVISIONED"

  read_capacity  = 5
  write_capacity = 5

  hash_key  = "pk"
  range_key = "sk"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  attribute {
    name = "gsi1pk"
    type = "S"
  }
  attribute {
    name = "gsi1sk"
    type = "S"
  }

  # Answers "show me recent postings" for the read API.
  # gsi1pk is bucketed by day (POSTED#2026-08-12) rather than a constant value,
  # which would concentrate every write into one partition.
  global_secondary_index {
    name            = "gsi1"
    projection_type = "ALL"

    read_capacity  = 5
    write_capacity = 5

    # `hash_key`/`range_key` are deprecated on this block in AWS provider 6.x
    # in favour of key_schema. Note the table's own top-level hash_key and
    # range_key are NOT deprecated and have no replacement yet — only the
    # index-level ones moved.
    key_schema {
      attribute_name = "gsi1pk"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "gsi1sk"
      key_type       = "RANGE"
    }
  }

  # Postings expire after 90 days. DynamoDB deletes expired items at no charge,
  # so the table stays inside the 25 GB free allowance without a cleanup job.
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  # Required for the notify Lambda in a later stage. NEW_IMAGE is enough —
  # notification only needs the posting that arrived, not what it replaced.
  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"

  point_in_time_recovery {
    # Off deliberately: PITR is billed per GB of backup and this data is
    # reproducible by re-running ingest. Paying to back up a cache would be
    # the wrong trade at a $0 budget.
    enabled = false
  }

  server_side_encryption {
    # AWS-owned key: encrypted at rest, no charge. A customer-managed CMK
    # would be ~$1/month, same reasoning as the state bucket (ADR 0002).
    enabled = false
  }

  tags = var.tags
}

output "name" { value = aws_dynamodb_table.this.name }
output "arn" { value = aws_dynamodb_table.this.arn }
output "stream_arn" { value = aws_dynamodb_table.this.stream_arn }
output "gsi_arn" { value = "${aws_dynamodb_table.this.arn}/index/gsi1" }
