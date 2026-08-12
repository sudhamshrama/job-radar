variable "name" { type = string }
variable "handler" { type = string }
variable "runtime" { type = string }
variable "source_dir" { type = string }
variable "environment" {
  type    = map(string)
  default = {}
}
variable "policy_statements" {
  description = "Least-privilege statements for this function's role."
  type = list(object({
    sid       = string
    actions   = list(string)
    resources = list(string)
  }))
  default = []
}
variable "timeout" {
  type    = number
  default = 60
}
variable "memory_size" {
  type    = number
  default = 256
}
variable "log_retention_days" {
  type    = number
  default = 14
}
variable "reserved_concurrency" {
  description = <<-EOT
    Per-function concurrency cap. -1 means unreserved.

    This defaults to -1 because reserving concurrency is IMPOSSIBLE on this
    account, not because it is undesirable. See ADR 0005.

    AWS requires at least 10 unreserved concurrent executions account-wide.
    This account's total limit is 10 (new accounts start far below the usual
    1000), so reserving even 1 would push unreserved to 9 and is rejected:

      InvalidParameterValueException: Specified ReservedConcurrentExecutions
      for function decreases account's UnreservedConcurrentExecution below its
      minimum value of [10].

    The account-wide limit of 10 is itself the runaway-invocation guardrail
    that a reservation would have provided — at account scope rather than
    function scope. Set this to a positive number once the quota is raised.
  EOT
  type        = number
  default     = -1
}
variable "tags" {
  type    = map(string)
  default = {}
}

# Packaged at plan time from the source tree. No build step, no container, no
# pip install: the code imports only the standard library, and boto3 ships with
# the Lambda runtime. That also sidesteps the classic trap of building a
# package on an arm64 Mac that then fails on an x86_64 runtime.
data "archive_file" "package" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "${path.module}/.build/${var.name}.zip"

  excludes = [
    "__pycache__",
    "**/__pycache__",
    "**/*.pyc",
  ]
}

resource "aws_iam_role" "this" {
  name = "${var.name}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = var.tags
}

# Written by hand rather than attaching AWSLambdaBasicExecutionRole, and scoped
# to this function's own log group. The managed policy grants logs:* on "*",
# which is broader than anything here needs.
resource "aws_iam_role_policy" "logs" {
  name = "${var.name}-logs"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "WriteOwnLogs"
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
      ]
      Resource = "${aws_cloudwatch_log_group.this.arn}:*"
    }]
  })
}

resource "aws_iam_role_policy" "custom" {
  count = length(var.policy_statements) > 0 ? 1 : 0

  name = "${var.name}-policy"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      for s in var.policy_statements : {
        Sid      = s.sid
        Effect   = "Allow"
        Action   = s.actions
        Resource = s.resources
      }
    ]
  })
}

# Created explicitly rather than letting Lambda auto-create it. An auto-created
# group has NO retention policy, so logs are kept forever and quietly grow past
# the 5 GB free allowance. This is one of the most common accidental serverless
# costs.
resource "aws_cloudwatch_log_group" "this" {
  # checkov:skip=CKV_AWS_158:KMS encryption of log groups requires a CMK
  # (~$1/month). Logs are encrypted at rest by CloudWatch by default. These
  # logs contain public job postings and counts, no personal or secret data.
  # checkov:skip=CKV_AWS_338:One year of retention directly contradicts the
  # cost constraint — the CloudWatch Logs free allowance is 5 GB, and this
  # function logs every source result every 6 hours. 14 days is long enough to
  # debug a failed run, which is what these logs are for. A compliance
  # environment with a retention requirement would set this differently.
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_lambda_function" "this" {
  # checkov:skip=CKV_AWS_115:Reserved concurrency is rejected by this account.
  # AWS requires >=10 unreserved concurrent executions and this account's total
  # limit IS 10, so any reservation is refused at apply time. The account-wide
  # limit provides the same runaway protection. See ADR 0005.
  # checkov:skip=CKV_AWS_272:Code signing needs an AWS Signer profile and a
  # signing step in CI. The package is built by Terraform from source in this
  # repo, and supply-chain signing is the subject of a later project rather
  # than a half-measure here.
  # checkov:skip=CKV_AWS_117:No VPC. A Lambda in a VPC needs a NAT Gateway to
  # reach the public job-board APIs, which is ~$32/month against a $0 budget.
  # The function holds no private data and talks only to public HTTPS APIs.
  # checkov:skip=CKV_AWS_173:Environment variables here are TABLE_NAME and
  # LOG_LEVEL — configuration, not secrets. AWS encrypts them at rest with an
  # AWS-managed key by default; a CMK would add ~$1/month to protect a table
  # name. Real secrets would go in SSM Parameter Store, not env vars.
  # checkov:skip=CKV_AWS_116:A Lambda DLQ is the right control and it is coming
  # in the next stage, where SQS + a DLQ sit between ingest and normalize.
  # Adding a second, separate DLQ here now would be a duplicate mechanism to
  # rip out a stage later. Until then, failed async invocations are covered by
  # the scheduler's retry policy and the total-failure alarm.
  function_name = var.name
  role          = aws_iam_role.this.arn
  handler       = var.handler
  runtime       = var.runtime

  filename         = data.archive_file.package.output_path
  source_code_hash = data.archive_file.package.output_base64sha256

  timeout                        = var.timeout
  memory_size                    = var.memory_size
  reserved_concurrent_executions = var.reserved_concurrency

  environment {
    variables = var.environment
  }

  tracing_config {
    # X-Ray: 100k traces/month always free.
    mode = "Active"
  }

  depends_on = [
    aws_cloudwatch_log_group.this,
    aws_iam_role_policy.logs,
  ]

  tags = var.tags
}

output "arn" { value = aws_lambda_function.this.arn }
output "name" { value = aws_lambda_function.this.function_name }
output "role_arn" { value = aws_iam_role.this.arn }
output "log_group" { value = aws_cloudwatch_log_group.this.name }
