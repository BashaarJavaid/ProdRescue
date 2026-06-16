variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "db_password" {
  description = "Master password for the RDS Postgres instance"
  type        = string
  sensitive   = true
}
