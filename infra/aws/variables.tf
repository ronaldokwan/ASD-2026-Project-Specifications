variable "aws_region" {
  description = "AWS region for the integrated group application."
  type        = string
  default     = "ap-southeast-2"
}

variable "name_prefix" {
  description = "Short prefix for AWS resource names."
  type        = string
  default     = "asd26-g40-r2"
}

variable "image_tag" {
  description = "Immutable source commit tag used by all ECR images."
  type        = string
  default     = "bootstrap"
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.40.0.0/20", "10.40.16.0/20"]
}

variable "private_subnet_cidrs" {
  type    = list(string)
  default = ["10.40.128.0/20", "10.40.144.0/20"]
}

variable "public_access_cidrs" {
  description = "CIDR ranges allowed to reach public frontend listeners. Narrow this before deployment."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "certificate_arn" {
  description = "Optional ACM certificate ARN; when set, port 80 redirects to HTTPS."
  type        = string
  default     = ""
}

variable "enable_vpc_endpoints" {
  description = "Use private ECR, S3 and CloudWatch Logs endpoints so tasks need no public IP or NAT."
  type        = bool
  default     = true
}

variable "task_cpu" {
  description = "Default Fargate CPU units per service."
  type        = number
  default     = 256
}

variable "task_memory" {
  description = "Default Fargate memory MiB per service."
  type        = number
  default     = 512
}

variable "student2_task_cpu" {
  type    = number
  default = 512
}

variable "student2_task_memory" {
  type    = number
  default = 1024
}

variable "desired_count" {
  description = "Tasks per service. Keep every SQLite database service at one task."
  type        = number
  default     = 1
  validation {
    condition     = var.desired_count == 1
    error_message = "SQLite database services are single-writer and must remain at one task."
  }
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "discovery_namespace" {
  type    = string
  default = "asd.internal"
}
