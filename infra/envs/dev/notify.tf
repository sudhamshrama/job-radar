# ---------------------------------------------------------------------------
# Notify path: DynamoDB Streams -> notify Lambda -> SNS email digest.
#
# This is where SQS earns its place in this project. A stream shard is
# processed IN ORDER, so a record that always raises is retried until it
# expires (up to 24h) and blocks every record behind it. Bounded retries plus a
# real dead-letter queue is the difference between "one bad item" and "no
# notifications for a day".
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "notify_dlq" {
  name = "${local.prefix}-notify-dlq"

  # 14 days, the maximum. A DLQ nobody reads before the messages expire is
  # decoration — this is the window to actually notice and investigate.
  message_retention_seconds = 1209600

  # SSE with the SQS-owned key: encrypted at rest, no KMS charge.
  sqs_managed_sse_enabled = true

  tags = local.tags
}

# NOTE: there is deliberately NO second "source" SQS queue here.
#
# The conventional SQS pattern is a source queue with a `redrive_policy`
# pointing at a DLQ. That does not apply to a DynamoDB Streams consumer: the
# stream IS the source, and Lambda writes failed batches straight to the DLQ
# via the event source mapping's `on_failure` destination below.
#
# A source queue was written here first and then deleted — nothing would have
# sent messages to it. It would have been a queue that existed because the
# pattern usually has one.

module "notify" {
  source = "../../modules/lambda_fn"

  name       = "${local.prefix}-notify"
  handler    = "job_radar.handlers.notify.handler"
  runtime    = var.python_runtime
  source_dir = local.source_dir

  timeout     = 30
  memory_size = 256

  environment = {
    TOPIC_ARN     = aws_sns_topic.alerts.arn
    DASHBOARD_URL = "https://${aws_cloudfront_distribution.site.domain_name}"
    LOG_LEVEL     = var.log_level
  }

  policy_statements = [
    {
      sid = "ReadStream"
      actions = [
        "dynamodb:GetRecords",
        "dynamodb:GetShardIterator",
        "dynamodb:DescribeStream",
        "dynamodb:ListStreams",
      ]
      resources = [module.jobs_table.stream_arn]
    },
    {
      sid       = "PublishDigest"
      actions   = ["sns:Publish"]
      resources = [aws_sns_topic.alerts.arn]
    },
    {
      sid       = "SendToDLQ"
      actions   = ["sqs:SendMessage"]
      resources = [aws_sqs_queue.notify_dlq.arn]
    },
    {
      sid       = "XRayTracing"
      actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
      resources = ["*"]
    },
  ]

  log_retention_days = var.log_retention_days
  tags               = local.tags
}

resource "aws_lambda_event_source_mapping" "notify" {
  event_source_arn  = module.jobs_table.stream_arn
  function_name     = module.notify.arn
  starting_position = "LATEST"

  # Batch up so one email covers a whole ingest run rather than one per job.
  batch_size                         = 100
  maximum_batching_window_in_seconds = 60

  # THE COST DECISION.
  #
  # Ingest rewrites ~200 items every run because writes are idempotent, so each
  # run emits ~200 MODIFY records and only a few INSERTs. Filtering here means
  # Lambda is never invoked for a MODIFY at all — filtering inside the handler
  # would still pay for the invocation.
  #
  # ~200 MODIFYs x 4 runs/day = ~800 invocations/day avoided.
  filter_criteria {
    filter {
      pattern = jsonencode({ eventName = ["INSERT"] })
    }
  }

  # Bound the blast radius of a poison record: without these, a record that
  # always fails is retried until it expires, blocking its shard.
  maximum_retry_attempts         = 3
  maximum_record_age_in_seconds  = 3600
  bisect_batch_on_function_error = true

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.notify_dlq.arn
    }
  }
}

# A DLQ with messages in it means notifications are silently broken. Nothing
# else surfaces that — the pipeline keeps ingesting perfectly well.
resource "aws_cloudwatch_metric_alarm" "notify_dlq_not_empty" {
  alarm_name          = "${local.prefix}-notify-dlq-not-empty"
  alarm_description   = "Messages in the notify DLQ: records failed processing repeatedly."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = { QueueName = aws_sqs_queue.notify_dlq.name }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}
