output "load_balancer_dns_name" {
  value       = aws_lb.app.dns_name
  description = "Public DNS for the shared home page."
}

output "frontend_urls" {
  value = {
    home      = "http://${aws_lb.app.dns_name}"
    student_1 = "http://${aws_lb.app.dns_name}:3001"
    student_2 = "http://${aws_lb.app.dns_name}:3002"
    student_3 = "http://${aws_lb.app.dns_name}:3003"
    student_4 = "http://${aws_lb.app.dns_name}:3004"
    student_5 = "http://${aws_lb.app.dns_name}:3005"
  }
}

output "database_filesystem_id" {
  value       = aws_efs_file_system.databases.id
  description = "Encrypted EFS filesystem mounted by the single-task SQLite services."
}

output "ecr_repository_urls" {
  value       = { for key, repository in aws_ecr_repository.services : key => repository.repository_url }
  description = "ECR repositories for immutable commit-tagged application images."
}
