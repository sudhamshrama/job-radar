output "table_name" { value = module.jobs_table.name }
output "table_stream_arn" { value = module.jobs_table.stream_arn }
output "ingest_function" { value = module.ingest.name }
output "ingest_log_group" { value = module.ingest.log_group }
output "alerts_topic" { value = aws_sns_topic.alerts.arn }
output "schedule" { value = aws_scheduler_schedule.ingest.schedule_expression }

output "invoke_command" {
  description = "Run ingest immediately instead of waiting for the schedule."
  value       = "aws lambda invoke --function-name ${module.ingest.name} --cli-binary-format raw-in-base64-out /dev/stdout"
}
