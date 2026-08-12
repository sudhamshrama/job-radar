variable "region" {
  type    = string
  default = "us-east-1"
}

variable "env" {
  type    = string
  default = "dev"
}

variable "python_runtime" {
  description = "Lambda runtime. Must be one AWS actually offers — the local Python version is irrelevant and, here, newer than anything Lambda supports."
  type        = string
  default     = "python3.13"
}

variable "schedule_expression" {
  description = "How often ingest runs. Every 6h keeps well inside the free tier while staying current."
  type        = string
  default     = "rate(6 hours)"
}

variable "alert_email" {
  type    = string
  default = "sudhamshrama03@gmail.com"
}

variable "log_level" {
  type    = string
  default = "INFO"
}

variable "log_retention_days" {
  description = "CloudWatch Logs free allowance is 5 GB. Never leave this unset — auto-created groups retain forever."
  type        = number
  default     = 14
}
