# Bonus cloud AI profile (B1-B4). Off by default: with enable_cloud_ai = false nothing in
# this file is created and every backend keeps AI-Mode, MCP, RAG and Multi-Agent disabled,
# which is the required Release 2 cloud baseline that cloud-deployment.yml deploys.
#
# When enabled, one private Fargate task runs Ollama plus the four shared AI services as
# separate containers that share localhost, exactly as they share the host locally. The
# backends reach them through Cloud Map (ai-services.asd.internal:7001-7004); Ollama only
# listens on 127.0.0.1, so nothing outside the task can call the model directly.

variable "enable_cloud_ai" {
  description = "Bonus profile: deploy AI-Mode, MCP, RAG, Multi-Agent and Ollama, and point the backends at them."
  type        = bool
  default     = false
}

variable "cloud_ai_image_tag" {
  description = "Immutable tag of the ai-services image (built from ai-services/Dockerfile.cloud)."
  type        = string
  default     = "bootstrap"
}

variable "cloud_ai_cpu" {
  description = "Fargate CPU units for the AI task; Ollama runs on CPU, so more vCPUs mean faster answers."
  type        = number
  default     = 16384
}

variable "cloud_ai_memory" {
  description = "Fargate memory MiB for the AI task (Ollama keeps both models loaded)."
  type        = number
  default     = 32768
}

variable "cloud_ai_models" {
  description = "Ollama models pulled when the task starts: AI-Mode/RAG/Worker and Planner/Reviewer."
  type        = string
  default     = "qwen2.5:3b llama3.1:8b"
}

locals {
  cloud_ai_host = "ai-services.${local.namespace}"

  # Only keys a backend already declares are switched on, so each student's service keeps
  # its own configuration contract (Student 2, 4 and 5 have no Multi-Agent settings).
  cloud_ai_backend_overrides = {
    AI_MODE_ENABLED     = "true", MCP_ENABLED = "true", RAG_ENABLED = "true"
    MULTI_AGENT_ENABLED = "true"
    AI_MODE_URL         = "http://${local.cloud_ai_host}:7001"
    MCP_SERVER_URL      = "http://${local.cloud_ai_host}:7002"
    RAG_SERVER_URL      = "http://${local.cloud_ai_host}:7003"
    MULTI_AGENT_URL     = "http://${local.cloud_ai_host}:7004"
  }
  service_environment = {
    for key, value in local.services : key => (
      var.enable_cloud_ai && value.role == "backend"
      ? merge(value.environment, {
        for name, setting in local.cloud_ai_backend_overrides : name => setting
        if contains(keys(value.environment), name)
      })
      : value.environment
    )
  }

  cloud_ai_common_environment = {
    OLLAMA_URL                 = "http://127.0.0.1:11434"
    MULTI_AGENT_OLLAMA_URL     = "http://127.0.0.1:11434"
    LLM_MODEL                  = "qwen2.5:3b"
    REVIEW_MODEL               = "llama3.1:8b"
    MULTI_AGENT_PLANNER_MODEL  = "llama3.1:8b"
    MULTI_AGENT_WORKER_MODEL   = "qwen2.5:3b"
    MULTI_AGENT_REVIEWER_MODEL = "llama3.1:8b"
    LLM_TIMEOUT                = "300"
    MULTI_AGENT_STAGE_TIMEOUT  = "300"
    AI_MODE_REVIEW_DATA_DIR    = "/tmp/ai-data/agentic-reviews"
    MULTI_AGENT_DATA_DIR       = "/tmp/ai-data/multi-agent"
    MCP_ALLOWED_HOSTS          = "${local.cloud_ai_host},${local.cloud_ai_host}:*"
  }
  cloud_ai_services = {
    "ai-mode"     = { port = 7001, script = "app.py" }
    "mcp-server"  = { port = 7002, script = "server.py" }
    "rag-server"  = { port = 7003, script = "http_server.py" }
    "multi-agent" = { port = 7004, script = "server.py" }
  }
}

resource "aws_ecr_repository" "cloud_ai" {
  count                = var.enable_cloud_ai ? 1 : 0
  name                 = "${var.name_prefix}/ai-services"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
  tags = { Application = "asd-group-application", Service = "ai-services" }
}

resource "aws_cloudwatch_log_group" "cloud_ai" {
  count             = var.enable_cloud_ai ? 1 : 0
  name              = "/ecs/${var.name_prefix}/ai-services"
  retention_in_days = var.log_retention_days
  tags              = { Service = "ai-services" }
}

# Ollama downloads its models and image on start. A NAT gateway gives the private task
# outbound-only internet access, so no task needs a public IP and inbound stays closed.
resource "aws_eip" "cloud_ai_nat" {
  count  = var.enable_cloud_ai ? 1 : 0
  domain = "vpc"
  tags   = { Name = "${var.name_prefix}-ai-nat" }
}

resource "aws_nat_gateway" "cloud_ai" {
  count         = var.enable_cloud_ai ? 1 : 0
  allocation_id = aws_eip.cloud_ai_nat[0].id
  subnet_id     = aws_subnet.public[0].id
  tags          = { Name = "${var.name_prefix}-ai-nat" }
  depends_on    = [aws_internet_gateway.app]
}

resource "aws_route" "private_nat" {
  count                  = var.enable_cloud_ai ? 2 : 0
  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.cloud_ai[0].id
}

resource "aws_ecs_task_definition" "cloud_ai" {
  count                    = var.enable_cloud_ai ? 1 : 0
  family                   = "${var.name_prefix}-ai-services"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cloud_ai_cpu
  memory                   = var.cloud_ai_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  ephemeral_storage {
    size_in_gib = 60
  }
  container_definitions = jsonencode(concat([{
    name       = "ollama"
    image      = "ollama/ollama:0.32.9"
    essential  = true
    entryPoint = ["/bin/sh", "-c"]
    command = [join(" ", [
      "ollama serve & until ollama list >/dev/null 2>&1; do sleep 1; done;",
      "for model in $AI_PULL_MODELS; do ollama pull \"$model\" || exit 1; done;",
      "touch /tmp/models-ready; wait",
    ])]
    environment = [
      { name = "OLLAMA_HOST", value = "127.0.0.1:11434" },
      { name = "OLLAMA_KEEP_ALIVE", value = "-1" },
      { name = "OLLAMA_MAX_LOADED_MODELS", value = "2" },
      { name = "AI_PULL_MODELS", value = var.cloud_ai_models },
    ]
    healthCheck = {
      command     = ["CMD-SHELL", "test -f /tmp/models-ready"]
      interval    = 30
      timeout     = 5
      retries     = 10
      startPeriod = 300
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.cloud_ai[0].name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ollama"
      }
    }
    }], [for name, service in local.cloud_ai_services : {
    name             = name
    image            = "${aws_ecr_repository.cloud_ai[0].repository_url}:${var.cloud_ai_image_tag}"
    essential        = true
    workingDirectory = "/srv/${name}"
    command          = ["python", service.script]
    portMappings     = [{ containerPort = service.port, hostPort = service.port, protocol = "tcp" }]
    dependsOn        = [{ containerName = "ollama", condition = "START" }]
    environment = [for key, value in merge(local.cloud_ai_common_environment, { SERVICE_PORT = tostring(service.port) }) : {
      name = key, value = value
    }]
    # Liveness only: /health answers 503 until Ollama has its models, which would make ECS
    # replace the task mid-download. validate-cloud-ai.sh checks real readiness.
    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import socket; socket.create_connection(('127.0.0.1', ${service.port}), 3)\""]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.cloud_ai[0].name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = name
      }
    }
  }]))
  depends_on = [aws_iam_role_policy_attachment.execution]
  tags       = { Service = "ai-services", ImageCommit = var.cloud_ai_image_tag }
}

resource "aws_service_discovery_service" "cloud_ai" {
  count = var.enable_cloud_ai ? 1 : 0
  name  = "ai-services"
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

resource "aws_ecs_service" "cloud_ai" {
  count                              = var.enable_cloud_ai ? 1 : 0
  name                               = "${var.name_prefix}-ai-services"
  cluster                            = aws_ecs_cluster.app.id
  task_definition                    = aws_ecs_task_definition.cloud_ai[0].arn
  desired_count                      = 1
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
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
    registry_arn = aws_service_discovery_service.cloud_ai[0].arn
  }
  depends_on = [aws_route.private_nat, aws_vpc_endpoint.interface]
}

output "cloud_ai_enabled" {
  value = var.enable_cloud_ai
}
