data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs        = slice(data.aws_availability_zones.available.names, 0, 2)
  namespace  = var.discovery_namespace
  app_scheme = var.certificate_arn == "" ? "http" : "https"
  home_url   = "${local.app_scheme}://${aws_lb.app.dns_name}"

  services = {
    "shared-home" = {
      role           = "home", port = 80, listener_port = 80, health_path = "/", health_kind = "nginx"
      discovery_name = "", persistent = false, db_file = "", environment = {}
    }
    "student-1-db" = {
      role          = "database", port = 9001, health_path = "/health", health_kind = "python"
      listener_port = null, discovery_name = "student-1-db", persistent = true, db_file = "products.db"
      environment   = { DB_PATH = "/data/products.db", SERVICE_PORT = "9001" }
    }
    "student-1-backend" = {
      role          = "backend", port = 8001, health_path = "/health", health_kind = "python"
      listener_port = null, discovery_name = "student-1-backend", persistent = false, db_file = ""
      environment = {
        DATABASE_URL    = "http://student-1-db.${local.namespace}:9001", SERVICE_PORT = "8001"
        AI_MODE_ENABLED = "false", MCP_ENABLED = "false", RAG_ENABLED = "false"
        AI_MODE_URL     = "http://127.0.0.1:7001", MCP_SERVER_URL = "http://127.0.0.1:7002"
        RAG_SERVER_URL  = "http://127.0.0.1:7003"
      }
    }
    "student-1-frontend" = {
      role           = "frontend", port = 3001, listener_port = 3001, health_path = "/health", health_kind = "python"
      discovery_name = "", persistent = false, db_file = ""
      environment    = { BACKEND_URL = "http://student-1-backend.${local.namespace}:8001", HOME_URL = "" }
    }
    "student2-db" = {
      role          = "database", port = 9002, health_path = "/actuator/health", health_kind = "java"
      listener_port = null, discovery_name = "student2-db", persistent = true, db_file = "orders.db"
      environment   = { DATABASE_URL = "jdbc:sqlite:/data/orders.db", SERVER_PORT = "9002" }
    }
    "student2-api" = {
      role          = "backend", port = 8002, health_path = "/actuator/health", health_kind = "java"
      listener_port = null, discovery_name = "student2-api", persistent = false, db_file = ""
      environment = {
        SERVER_PORT     = "8002", DATABASE_API_URL = "http://student2-db.${local.namespace}:9002"
        PRODUCT_API_URL = "http://student-1-backend.${local.namespace}:8001"
        STOCK_API_URL   = "http://student-4-backend.${local.namespace}:8004"
        AI_MODE_URL     = "http://127.0.0.1:7001", MCP_SERVER_URL = "http://127.0.0.1:7002"
        RAG_SERVER_URL  = "http://127.0.0.1:7003", AI_MODE_ENABLED = "false"
        MCP_ENABLED     = "false", RAG_ENABLED = "false"
      }
    }
    "student2-frontend" = {
      role           = "frontend", port = 3002, listener_port = 3002, health_path = "/actuator/health", health_kind = "java"
      discovery_name = "", persistent = false, db_file = ""
      environment    = { SERVER_PORT = "3002", BACKEND_URL = "http://student2-api.${local.namespace}:8002" }
    }
    "student-3-db" = {
      role          = "database", port = 9003, health_path = "/health", health_kind = "python"
      listener_port = null, discovery_name = "student-3-db", persistent = true, db_file = "customers.db"
      environment   = { DB_PATH = "/data/customers.db", SERVICE_PORT = "9003" }
    }
    "student-3-backend" = {
      role          = "backend", port = 8003, health_path = "/health", health_kind = "python"
      listener_port = null, discovery_name = "student-3-backend", persistent = false, db_file = ""
      environment = {
        DATABASE_URL        = "http://student-3-db.${local.namespace}:9003", SERVICE_PORT = "8003"
        AI_MODE_ENABLED     = "false", MCP_ENABLED = "false", RAG_ENABLED = "false"
        MULTI_AGENT_ENABLED = "false", MULTI_AGENT_URL = "http://127.0.0.1:7004"
        AI_MODE_URL         = "http://127.0.0.1:7001", MCP_SERVER_URL = "http://127.0.0.1:7002"
        RAG_SERVER_URL      = "http://127.0.0.1:7003"
      }
    }
    "student-3-frontend" = {
      role           = "frontend", port = 3003, listener_port = 3003, health_path = "/health", health_kind = "python"
      discovery_name = "", persistent = false, db_file = ""
      environment    = { BACKEND_URL = "http://student-3-backend.${local.namespace}:8003", HOME_URL = "" }
    }
    "student-4-db" = {
      role          = "database", port = 9004, health_path = "/health", health_kind = "python"
      listener_port = null, discovery_name = "student-4-db", persistent = true, db_file = "stock.db"
      environment   = { DB_PATH = "/data/stock.db", SERVICE_PORT = "9004" }
    }
    "student-4-backend" = {
      role          = "backend", port = 8004, health_path = "/health", health_kind = "python"
      listener_port = null, discovery_name = "student-4-backend", persistent = false, db_file = ""
      environment = {
        DATABASE_URL    = "http://student-4-db.${local.namespace}:9004", SERVICE_PORT = "8004"
        AI_MODE_ENABLED = "false", MCP_ENABLED = "false", RAG_ENABLED = "false"
        AI_MODE_URL     = "http://127.0.0.1:7001", MCP_SERVER_URL = "http://127.0.0.1:7002"
        RAG_SERVER_URL  = "http://127.0.0.1:7003"
      }
    }
    "student-4-frontend" = {
      role           = "frontend", port = 3004, listener_port = 3004, health_path = "/health", health_kind = "python"
      discovery_name = "", persistent = false, db_file = ""
      environment    = { BACKEND_URL = "http://student-4-backend.${local.namespace}:8004", HOME_URL = "" }
    }
    "student-5-db" = {
      role          = "database", port = 9005, health_path = "/health", health_kind = "python"
      listener_port = null, discovery_name = "student-5-db", persistent = true, db_file = "reviews.db"
      environment   = { DB_PATH = "/data/reviews.db", SERVICE_PORT = "9005" }
    }
    "student-5-backend" = {
      role          = "backend", port = 8005, health_path = "/health", health_kind = "python"
      listener_port = null, discovery_name = "student-5-backend", persistent = false, db_file = ""
      environment = {
        DATABASE_URL    = "http://student-5-db.${local.namespace}:9005", SERVICE_PORT = "8005"
        CATALOGUE_URL   = "http://student-1-backend.${local.namespace}:8001"
        AI_MODE_ENABLED = "false", MCP_ENABLED = "false", RAG_ENABLED = "false"
        AI_MODE_URL     = "http://127.0.0.1:7001", MCP_SERVER_URL = "http://127.0.0.1:7002"
        RAG_SERVER_URL  = "http://127.0.0.1:7003"
      }
    }
    "student-5-frontend" = {
      role           = "frontend", port = 3005, listener_port = 3005, health_path = "/health", health_kind = "python"
      discovery_name = "", persistent = false, db_file = ""
      environment    = { BACKEND_URL = "http://student-5-backend.${local.namespace}:8005", HOME_URL = "" }
    }
  }

  databases              = { for key, value in local.services : key => value if value.role == "database" }
  backends               = { for key, value in local.services : key => value if value.role == "backend" }
  frontends              = { for key, value in local.services : key => value if contains(["frontend", "home"], value.role) }
  databases_and_backends = { for key, value in local.services : key => value if contains(["database", "backend"], value.role) }
  persistent_services    = local.databases
}

resource "aws_vpc" "app" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = { Name = "${var.name_prefix}-vpc" }
}

resource "aws_internet_gateway" "app" {
  vpc_id = aws_vpc.app.id
  tags   = { Name = "${var.name_prefix}-igw" }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.app.id
  availability_zone       = local.azs[count.index]
  cidr_block              = var.public_subnet_cidrs[count.index]
  map_public_ip_on_launch = true
  tags                    = { Name = "${var.name_prefix}-public-${count.index + 1}" }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.app.id
  availability_zone = local.azs[count.index]
  cidr_block        = var.private_subnet_cidrs[count.index]
  tags              = { Name = "${var.name_prefix}-private-${count.index + 1}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.app.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.app.id
  }
  tags = { Name = "${var.name_prefix}-public" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  count  = 2
  vpc_id = aws_vpc.app.id
  tags   = { Name = "${var.name_prefix}-private-${count.index + 1}" }
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

resource "aws_security_group" "alb" {
  name        = "${var.name_prefix}-alb"
  description = "Public access only to the home page and frontend listeners."
  vpc_id      = aws_vpc.app.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${var.name_prefix}-alb" }
}

resource "aws_security_group_rule" "alb_http" {
  type              = "ingress"
  security_group_id = aws_security_group.alb.id
  from_port         = 80
  to_port           = 80
  protocol          = "tcp"
  cidr_blocks       = var.public_access_cidrs
}

resource "aws_security_group_rule" "alb_frontend_ports" {
  for_each          = { for key, value in local.frontends : key => value if value.role == "frontend" }
  type              = "ingress"
  security_group_id = aws_security_group.alb.id
  from_port         = each.value.listener_port
  to_port           = each.value.listener_port
  protocol          = "tcp"
  cidr_blocks       = var.public_access_cidrs
}

resource "aws_security_group" "tasks" {
  name        = "${var.name_prefix}-tasks"
  description = "Private Fargate services; only the ALB and other application tasks can connect."
  vpc_id      = aws_vpc.app.id
  ingress {
    description = "Application service-to-service traffic."
    from_port   = 1
    to_port     = 65535
    protocol    = "tcp"
    self        = true
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${var.name_prefix}-tasks" }
}

resource "aws_security_group_rule" "tasks_frontend_from_alb" {
  for_each                 = { for key, value in local.frontends : key => value if value.role == "frontend" }
  type                     = "ingress"
  security_group_id        = aws_security_group.tasks.id
  source_security_group_id = aws_security_group.alb.id
  from_port                = each.value.port
  to_port                  = each.value.port
  protocol                 = "tcp"
}

resource "aws_security_group" "endpoint" {
  count       = var.enable_vpc_endpoints ? 1 : 0
  name        = "${var.name_prefix}-endpoints"
  description = "TLS access to private AWS service endpoints from Fargate tasks."
  vpc_id      = aws_vpc.app.id
  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.tasks.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "efs" {
  name        = "${var.name_prefix}-efs"
  description = "NFS only from the application task security group."
  vpc_id      = aws_vpc.app.id
  ingress {
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.tasks.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "app" {
  name               = substr("${var.name_prefix}-alb", 0, 32)
  load_balancer_type = "application"
  internal           = false
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]
  tags               = { Name = "${var.name_prefix}-alb" }
}

resource "aws_service_discovery_private_dns_namespace" "app" {
  name        = var.discovery_namespace
  description = "Private service discovery for the ASD group application."
  vpc         = aws_vpc.app.id
}

resource "aws_ecs_cluster" "app" {
  name = "${var.name_prefix}-cluster"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = { Name = "${var.name_prefix}-cluster" }
}

resource "aws_ecr_repository" "services" {
  for_each             = local.services
  name                 = "${var.name_prefix}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
  tags = { Application = "asd-group-application", Service = each.key }
}

resource "aws_cloudwatch_log_group" "services" {
  for_each          = local.services
  name              = "/ecs/${var.name_prefix}/${each.key}"
  retention_in_days = var.log_retention_days
  tags              = { Service = each.key }
}

resource "aws_efs_file_system" "databases" {
  creation_token   = "${var.name_prefix}-sqlite"
  encrypted        = true
  performance_mode = "generalPurpose"
  throughput_mode  = "elastic"
  lifecycle_policy { transition_to_ia = "AFTER_30_DAYS" }
  tags = { Name = "${var.name_prefix}-database-data", Purpose = "durable-single-writer-sqlite" }
}

resource "aws_efs_access_point" "databases" {
  for_each       = local.persistent_services
  file_system_id = aws_efs_file_system.databases.id
  posix_user {
    uid = 1000
    gid = 1000
  }
  root_directory {
    path = "/${each.key}"
    creation_info {
      owner_uid   = 1000
      owner_gid   = 1000
      permissions = "0750"
    }
  }
  tags = { Name = "${var.name_prefix}-${each.key}-data" }
}

resource "aws_efs_mount_target" "private" {
  count           = 2
  file_system_id  = aws_efs_file_system.databases.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.efs.id]
}

resource "aws_iam_role" "execution" {
  name = "${var.name_prefix}-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" },
    Action = "sts:AssumeRole" }],
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name = "${var.name_prefix}-task"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" },
    Action = "sts:AssumeRole" }],
  })
}

resource "aws_iam_role_policy" "efs_client" {
  name = "${var.name_prefix}-efs-client"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{ Effect = "Allow",
      Action   = ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite"],
      Resource = aws_efs_file_system.databases.arn,
      Condition = { StringEquals = {
        "elasticfilesystem:AccessPointArn" = [for point in aws_efs_access_point.databases : point.arn]
      } },
    }],
  })
}

resource "aws_ecs_task_definition" "service" {
  for_each                 = local.services
  family                   = "${var.name_prefix}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = startswith(each.key, "student2-") ? var.student2_task_cpu : var.task_cpu
  memory                   = startswith(each.key, "student2-") ? var.student2_task_memory : var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name         = each.key
    image        = "${aws_ecr_repository.services[each.key].repository_url}:${var.image_tag}"
    essential    = true
    portMappings = [{ containerPort = each.value.port, hostPort = each.value.port, protocol = "tcp" }]
    environment = [for name, value in each.value.environment : {
      name  = name
      value = name == "HOME_URL" ? local.home_url : value
    }]
    mountPoints = each.value.persistent ? [{ sourceVolume = "database-data", containerPath = "/data", readOnly = false }] : []
    healthCheck = {
      command     = ["CMD-SHELL", each.value.health_kind == "python" ? "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:${each.value.port}${each.value.health_path}', timeout=3)\"" : each.value.health_kind == "java" ? "curl -fsS http://127.0.0.1:${each.value.port}${each.value.health_path} >/dev/null" : "wget -qO- http://127.0.0.1/ >/dev/null"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.services[each.key].name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = each.key
      }
    }
  }])
  dynamic "volume" {
    for_each = each.value.persistent ? [1] : []
    content {
      name = "database-data"
      efs_volume_configuration {
        file_system_id     = aws_efs_file_system.databases.id
        transit_encryption = "ENABLED"
        authorization_config {
          access_point_id = aws_efs_access_point.databases[each.key].id
          iam             = "ENABLED"
        }
      }
    }
  }
  depends_on = [aws_iam_role_policy_attachment.execution, aws_iam_role_policy.efs_client]
  tags       = { Service = each.key, ImageCommit = var.image_tag }
}

resource "aws_service_discovery_service" "internal" {
  for_each = local.databases_and_backends
  name     = each.value.discovery_name
  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.app.id
    routing_policy = "MULTIVALUE"
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
  health_check_custom_config {
    failure_threshold = 1
  }
}

resource "aws_lb_target_group" "frontend" {
  for_each    = local.frontends
  name        = substr("${var.name_prefix}-${each.key}", 0, 32)
  port        = each.value.port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.app.id
  health_check {
    path                = each.value.health_path
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
  tags = { Service = each.key }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = var.certificate_arn == "" ? "forward" : "redirect"
    target_group_arn = var.certificate_arn == "" ? aws_lb_target_group.frontend["shared-home"].arn : null
    dynamic "redirect" {
      for_each = var.certificate_arn == "" ? [] : [1]
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

resource "aws_lb_listener" "https" {
  count             = var.certificate_arn == "" ? 0 : 1
  load_balancer_arn = aws_lb.app.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend["shared-home"].arn
  }
}

resource "aws_security_group_rule" "alb_https" {
  count             = var.certificate_arn == "" ? 0 : 1
  type              = "ingress"
  security_group_id = aws_security_group.alb.id
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = var.public_access_cidrs
}

resource "aws_lb_listener" "frontends" {
  for_each          = { for key, value in local.frontends : key => value if value.role == "frontend" }
  load_balancer_arn = aws_lb.app.arn
  port              = each.value.listener_port
  protocol          = local.app_scheme == "https" ? "HTTPS" : "HTTP"
  certificate_arn   = var.certificate_arn == "" ? null : var.certificate_arn
  ssl_policy        = var.certificate_arn == "" ? null : "ELBSecurityPolicy-TLS13-1-2-2021-06"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend[each.key].arn
  }
}

resource "aws_ecs_service" "database" {
  for_each                           = local.databases
  name                               = "${var.name_prefix}-${each.key}"
  cluster                            = aws_ecs_cluster.app.id
  task_definition                    = aws_ecs_task_definition.service[each.key].arn
  desired_count                      = var.desired_count
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  health_check_grace_period_seconds  = 60
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }
  service_registries {
    registry_arn   = aws_service_discovery_service.internal[each.key].arn
    container_name = each.key
    container_port = each.value.port
  }
  depends_on = [aws_efs_mount_target.private, aws_vpc_endpoint.interface]
}

resource "aws_ecs_service" "backend" {
  for_each                           = local.backends
  name                               = "${var.name_prefix}-${each.key}"
  cluster                            = aws_ecs_cluster.app.id
  task_definition                    = aws_ecs_task_definition.service[each.key].arn
  desired_count                      = var.desired_count
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }
  service_registries {
    registry_arn   = aws_service_discovery_service.internal[each.key].arn
    container_name = each.key
    container_port = each.value.port
  }
  depends_on = [aws_ecs_service.database, aws_vpc_endpoint.interface]
}

resource "aws_ecs_service" "frontend" {
  for_each                           = local.frontends
  name                               = "${var.name_prefix}-${each.key}"
  cluster                            = aws_ecs_cluster.app.id
  task_definition                    = aws_ecs_task_definition.service[each.key].arn
  desired_count                      = var.desired_count
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }
  dynamic "load_balancer" {
    for_each = each.value.role == "frontend" || each.value.role == "home" ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.frontend[each.key].arn
      container_name   = each.key
      container_port   = each.value.port
    }
  }
  depends_on = [aws_ecs_service.backend, aws_lb_listener.http, aws_lb_listener.frontends]
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = var.enable_vpc_endpoints ? toset(["ecr.api", "ecr.dkr", "logs"]) : toset([])
  vpc_id              = aws_vpc.app.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.endpoint[0].id]
  tags                = { Name = "${var.name_prefix}-${replace(each.key, ".", "-")}" }
}

resource "aws_vpc_endpoint" "s3" {
  count             = var.enable_vpc_endpoints ? 1 : 0
  vpc_id            = aws_vpc.app.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.private[*].id
  tags              = { Name = "${var.name_prefix}-s3-endpoint" }
}
