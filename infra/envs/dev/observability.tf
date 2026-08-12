# ---------------------------------------------------------------------------
# Stage 7 — one dashboard that answers "is the pipeline healthy?"
#
# CloudWatch's free tier includes 3 dashboards, so this costs nothing. It is
# deliberately ONE dashboard: three specialised dashboards nobody opens are
# worth less than one that gets checked.
#
# Every widget answers a specific question rather than displaying a metric
# because the metric exists.
# ---------------------------------------------------------------------------

locals {
  dash_lambdas = [module.ingest.name, module.query.name, module.notify.name]
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = local.prefix

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "text", x = 0, y = 0, width = 24, height = 2
        properties = {
          markdown = join("\n", [
            "# job-radar — ${var.env}",
            "Dashboard: https://${aws_cloudfront_distribution.site.domain_name} · ",
            "Ingest runs ${var.schedule_expression}. ",
            "**Ingest errors are only raised when EVERY source fails** — a single retired job board is logged, not alarmed."
          ])
        }
      },

      # Q: is ingest actually running, and is it finding anything?
      {
        type = "metric", x = 0, y = 2, width = 12, height = 6
        properties = {
          title  = "Ingest — invocations vs errors"
          region = var.region
          view   = "timeSeries"
          stat   = "Sum"
          period = 3600
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", module.ingest.name],
            [".", "Errors", ".", "."],
            [".", "Throttles", ".", "."],
          ]
          yAxis = { left = { min = 0 } }
        }
      },

      # Q: how close is ingest to its 600s timeout? A run that creeps toward
      # the ceiling fails silently by truncating, not by erroring.
      {
        type = "metric", x = 12, y = 2, width = 12, height = 6
        properties = {
          title  = "Ingest duration vs 600s timeout"
          region = var.region
          view   = "timeSeries"
          period = 3600
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", module.ingest.name,
            { stat = "Maximum", label = "max" }],
            ["...", { stat = "Average", label = "avg" }],
          ]
          annotations = {
            horizontal = [{ label = "timeout", value = 600000, color = "#d62728" }]
          }
        }
      },

      # Q: is the public API up and fast?
      {
        type = "metric", x = 0, y = 8, width = 12, height = 6
        properties = {
          title  = "Read API — requests and errors"
          region = var.region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiId", aws_apigatewayv2_api.http.id],
            [".", "4xx", ".", "."],
            [".", "5xx", ".", "."],
          ]
        }
      },

      # Q: are we near the provisioned capacity that keeps this free?
      # Sustained throttling means the 5/5 RCU/WCU is too low.
      {
        type = "metric", x = 12, y = 8, width = 12, height = 6
        properties = {
          title  = "DynamoDB — consumed capacity and throttles"
          region = var.region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            ["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", module.jobs_table.name],
            [".", "ConsumedReadCapacityUnits", ".", "."],
            [".", "ThrottledRequests", ".", "."],
          ]
        }
      },

      # Q: are notifications silently broken? Nothing else surfaces this —
      # ingest keeps working perfectly while the digest stops arriving.
      {
        type = "metric", x = 0, y = 14, width = 12, height = 6
        properties = {
          title  = "Notify — invocations, errors, DLQ depth"
          region = var.region
          view   = "timeSeries"
          period = 300
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", module.notify.name, { stat = "Sum" }],
            [".", "Errors", ".", ".", { stat = "Sum" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName",
            aws_sqs_queue.notify_dlq.name, { stat = "Maximum", label = "DLQ depth" }],
          ]
        }
      },

      # Q: which sources failed on the last run?
      # Structured JSON logging is what makes this query possible at all —
      # a plain-text log line would not be parseable into fields.
      {
        type = "log", x = 12, y = 14, width = 12, height = 6
        properties = {
          title  = "Recent source failures (last 24h)"
          region = var.region
          query = join(" | ", [
            "SOURCE '${module.ingest.log_group}'",
            "fields @timestamp, source, error",
            "filter message = 'source failed'",
            "sort @timestamp desc",
            "limit 20",
          ])
          view = "table"
        }
      },
    ]
  })
}

# Alarms fire on SNS; this makes the same state visible without email.
output "dashboard_console_url" {
  value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards/dashboard/${local.prefix}"
}

output "lambda_functions" {
  value = local.dash_lambdas
}
