# GitHub Actions deploy role for cloud-deployment.yml.
# Applied once, by an account administrator, with scripts/aws/setup-github-oidc.sh.
# Kept out of ../ (the application stack) so the role never manages itself.

data "aws_caller_identity" "current" {}

locals {
  account_id    = data.aws_caller_identity.current.account_id
  oidc_url      = "https://token.actions.githubusercontent.com"
  provider_arn  = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
  app_role_arns = "arn:aws:iam::${local.account_id}:role/${var.name_prefix}-*"
  state_key     = "asd-2026/group-application"
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_oidc_provider ? 1 : 0
  url            = local.oidc_url
  client_id_list = ["sts.amazonaws.com"]
  # No thumbprint_list: AWS validates GitHub's certificate against its own trusted CAs.
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 0 : 1
  url   = local.oidc_url
}

resource "aws_iam_role" "github_deploy" {
  name                 = "${var.name_prefix}-github-deploy"
  description          = "Assumed by cloud-deployment.yml (environment ${var.github_environment}) to deploy the group application."
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Federated = local.provider_arn },
      Action    = "sts:AssumeRoleWithWebIdentity",
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com",
          # A job that names an environment gets this subject, so only the deploy job matches.
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:environment:${var.github_environment}"
        }
      }
    }],
  })
}

resource "aws_iam_role_policy" "github_deploy" {
  name = "${var.name_prefix}-github-deploy"
  role = aws_iam_role.github_deploy.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        # bootstrap-state.sh verifies the bucket; init.sh reads and locks the state.
        Sid    = "TerraformStateBucket",
        Effect = "Allow",
        Action = ["s3:ListBucket", "s3:GetBucketPublicAccessBlock", "s3:GetBucketVersioning",
        "s3:GetEncryptionConfiguration", "s3:GetBucketPolicy", "s3:GetBucketLocation"],
        Resource = "arn:aws:s3:::${var.tf_state_bucket}"
      },
      {
        Sid      = "TerraformStateObjects",
        Effect   = "Allow",
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
        Resource = "arn:aws:s3:::${var.tf_state_bucket}/${local.state_key}/*"
      },
      {
        # Everything infra/aws/main.tf creates, plus ECR pushes, in the deployment region only.
        Sid    = "ApplicationServicesInRegion",
        Effect = "Allow",
        Action = ["ec2:*", "elasticloadbalancing:*", "ecs:*", "ecr:*", "elasticfilesystem:*",
        "servicediscovery:*", "logs:*"],
        Resource  = "*",
        Condition = { StringEquals = { "aws:RequestedRegion" = var.aws_region } }
      },
      {
        # Cloud Map's private DNS namespace is a Route 53 private hosted zone (a global service).
        Sid    = "CloudMapHostedZone",
        Effect = "Allow",
        Action = ["route53:CreateHostedZone", "route53:DeleteHostedZone", "route53:GetHostedZone",
          "route53:ListHostedZonesByName", "route53:ChangeResourceRecordSets", "route53:ListResourceRecordSets",
          "route53:GetChange", "route53:AssociateVPCWithHostedZone", "route53:DisassociateVPCFromHostedZone",
        "route53:ChangeTagsForResource", "route53:ListTagsForResource"],
        Resource = "*"
      },
      {
        # The ECS task and execution roles, limited to the application's name prefix.
        Sid    = "ApplicationRoles",
        Effect = "Allow",
        Action = ["iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:UntagRole",
          "iam:UpdateRole", "iam:UpdateAssumeRolePolicy", "iam:PutRolePolicy", "iam:GetRolePolicy",
          "iam:DeleteRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
        "iam:ListInstanceProfilesForRole", "iam:DetachRolePolicy"],
        Resource = local.app_role_arns
      },
      {
        Sid       = "AttachOnlyTaskExecutionPolicy",
        Effect    = "Allow",
        Action    = "iam:AttachRolePolicy",
        Resource  = local.app_role_arns,
        Condition = { ArnEquals = { "iam:PolicyARN" = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy" } }
      },
      {
        Sid       = "PassRolesToEcsTasks",
        Effect    = "Allow",
        Action    = "iam:PassRole",
        Resource  = local.app_role_arns,
        Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } }
      },
      {
        Sid      = "ServiceLinkedRoles",
        Effect   = "Allow",
        Action   = "iam:CreateServiceLinkedRole",
        Resource = "*",
        Condition = { StringEquals = { "iam:AWSServiceName" = [
          "ecs.amazonaws.com", "elasticloadbalancing.amazonaws.com", "elasticfilesystem.amazonaws.com"
        ] } }
      },
      {
        # The deploy role must not edit itself.
        Sid      = "DenySelfModification",
        Effect   = "Deny",
        Action   = "iam:*",
        Resource = "arn:aws:iam::${local.account_id}:role/${var.name_prefix}-github-deploy"
      }
    ]
  })
}
