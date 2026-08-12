terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  backend "s3" {
    bucket       = "job-radar-tfstate-428625199448"
    key          = "dev/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = local.tags
  }
}

locals {
  prefix = "job-radar-${var.env}"

  tags = {
    Project   = "job-radar"
    Env       = var.env
    ManagedBy = "terraform"
  }

  # Everything under src/ becomes the deployment package: the job_radar package
  # plus config/sources.json, which lands at /var/task/config/sources.json.
  source_dir = "${path.root}/../../../src"
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

module "jobs_table" {
  source = "../../modules/table"

  name = "${local.prefix}-jobs"
  tags = local.tags
}

# ---------------------------------------------------------------------------
# Ingest function
# ---------------------------------------------------------------------------

module "ingest" {
  source = "../../modules/lambda_fn"

  name       = "${local.prefix}-ingest"
  handler    = "job_radar.handlers.ingest.handler"
  runtime    = var.python_runtime
  source_dir = local.source_dir

  # Fourteen sources fetched serially, each retrying up to 3 times with
  # backoff. The HN thread alone is a 2-call sequence over a large payload.
  timeout     = 300
  memory_size = 512

  environment = {
    TABLE_NAME = module.jobs_table.name
    LOG_LEVEL  = var.log_level
  }

  policy_statements = [
    {
      sid       = "WriteJobs"
      actions   = ["dynamodb:PutItem", "dynamodb:BatchWriteItem"]
      resources = [module.jobs_table.arn]
    },
    {
      sid = "XRayTracing"
      actions = [
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
      ]
      # X-Ray's API is account-level and does not accept resource ARNs.
      resources = ["*"]
    },
  ]

  log_retention_days = var.log_retention_days
  tags               = local.tags
}

# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

resource "aws_iam_role" "scheduler" {
  name = "${local.prefix}-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "scheduler.amazonaws.com" }
      # Without this, any account whose scheduler is configured with this
      # role's ARN could invoke it — the confused deputy problem. The condition
      # restricts assumption to schedules in this account.
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name = "${local.prefix}-scheduler-invoke"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = module.ingest.arn
    }]
  })
}

resource "aws_scheduler_schedule" "ingest" {
  # checkov:skip=CKV_AWS_297:A customer-managed KMS key is ~$1/month. The
  # schedule carries no payload beyond an empty event; there is nothing
  # sensitive to encrypt. EventBridge encrypts with an AWS-owned key by default.
  name       = "${local.prefix}-ingest"
  group_name = "default"

  flexible_time_window {
    # Nothing here is time-critical. A 15-minute window lets AWS spread the
    # invocation, which is friendlier to the public APIs being polled.
    mode                      = "FLEXIBLE"
    maximum_window_in_minutes = 15
  }

  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = "America/Chicago"

  target {
    arn      = module.ingest.arn
    role_arn = aws_iam_role.scheduler.arn

    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }
}

# ---------------------------------------------------------------------------
# Alarms
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name = "${local.prefix}-alerts"

  # AWS-managed KMS key, not a customer-managed one. AWS-managed keys carry no
  # monthly charge (unlike the ~$1/mo CMK declined elsewhere), and alarm
  # traffic is a handful of messages a month — far inside the KMS free tier.
  # Encryption here is genuinely free, so there is no reason not to have it.
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
  # Confirmation arrives by email and must be clicked. Terraform will show this
  # as "pending confirmation" until then.
}

# Fires when the handler raises — which, by design, only happens when EVERY
# source failed. A single retired job board is logged, not alarmed. An alarm
# that fires on routine partial failure gets muted within a week, and then it
# is not an alarm.
resource "aws_cloudwatch_metric_alarm" "ingest_failed" {
  alarm_name          = "${local.prefix}-ingest-total-failure"
  alarm_description   = "Ingest raised: all sources failed. Systemic, not one dead board."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = { FunctionName = module.ingest.name }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# The schedule silently not running is the failure you never notice, because
# nothing errors — the data just goes stale. Alarm on absence of invocations.
resource "aws_cloudwatch_metric_alarm" "ingest_not_running" {
  alarm_name          = "${local.prefix}-ingest-not-running"
  alarm_description   = "No ingest invocations in 24h — the schedule has stopped firing."
  namespace           = "AWS/Lambda"
  metric_name         = "Invocations"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"

  dimensions = { FunctionName = module.ingest.name }

  alarm_actions = [aws_sns_topic.alerts.arn]
}
