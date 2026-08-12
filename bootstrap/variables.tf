variable "region" {
  description = "AWS region for the state bucket. Must match the backend config in infra/envs/*."
  type        = string
  default     = "us-east-1"
}

variable "account_id" {
  description = "AWS account ID, used to make the bucket name globally unique."
  type        = string
  default     = "428625199448"
}
