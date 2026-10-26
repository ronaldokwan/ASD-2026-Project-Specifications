output "deploy_role_arn" {
  value       = aws_iam_role.github_deploy.arn
  description = "Set as the AWS_DEPLOY_ROLE_ARN variable of the aws-production GitHub environment."
}

output "github_subject" {
  value       = "repo:${var.github_repository}:environment:${var.github_environment}"
  description = "The only GitHub OIDC subject allowed to assume the deploy role."
}
