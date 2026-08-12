output "state_bucket" {
  description = "Name of the S3 bucket holding Terraform state. Goes in the backend block of infra/envs/*."
  value       = aws_s3_bucket.tfstate.id
}

output "backend_config" {
  description = "Copy-paste backend block for an environment configuration."
  value       = <<-EOT
    terraform {
      backend "s3" {
        bucket       = "${aws_s3_bucket.tfstate.id}"
        key          = "<env>/terraform.tfstate"
        region       = "${var.region}"
        encrypt      = true
        use_lockfile = true
      }
    }
  EOT
}
