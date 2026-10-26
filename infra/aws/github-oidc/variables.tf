variable "aws_region" {
  description = "Region the group application is deployed to; the deploy role is limited to it."
  type        = string
  default     = "ap-southeast-2"
}

variable "name_prefix" {
  description = "Must match name_prefix in ../variables.tf: the role may only manage IAM roles with this prefix."
  type        = string
  default     = "asd26-g40-r2"
}

variable "github_repository" {
  description = "owner/name of the repository whose cloud-deployment.yml may assume the role."
  type        = string
  default     = "ronaldokwan/ASD-2026-Project-Specifications"
}

variable "github_environment" {
  description = "GitHub environment the deploy job runs in; only that job can assume the role."
  type        = string
  default     = "aws-production"
}

variable "tf_state_bucket" {
  description = "Terraform state bucket used by scripts/aws/init.sh (TF_STATE_BUCKET)."
  type        = string
}

variable "create_oidc_provider" {
  description = "An account holds one GitHub OIDC provider; set false if it already exists."
  type        = bool
  default     = true
}
