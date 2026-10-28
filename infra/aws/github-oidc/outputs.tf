output "deploy_role_arn" {
  value       = aws_iam_role.github_deploy.arn
  description = "Set as the AWS_DEPLOY_ROLE_ARN variable of the aws-production GitHub environment."
}

output "github_subjects" {
  value = [
    "repo:${var.github_repository}:environment:${var.github_environment}",
    "repo:${var.github_immutable_repository}:environment:${var.github_environment}",
  ]
  description = "The only GitHub OIDC subjects (classic and immutable format) allowed to assume the deploy role."
}
