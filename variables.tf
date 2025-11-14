variable "project_name" {
  description = "Name prefix for all resources"
  type        = string
  default     = "selfserve-ui"
}

variable "aws_region" {
  description = "AWS region to deploy to"
  type        = string
  default     = "us-west-2"
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "List of 2 public subnet CIDRs"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "app_port" {
  description = "Port the container listens on"
  type        = number
  default     = 80
}

variable "ecr_repo_name" {
  description = "ECR repository name for the Angular UI"
  type        = string
  default     = "selfserve-angular-ui"
}

variable "container_cpu" {
  description = "Fargate task CPU units"
  type        = number
  default     = 256
}

variable "container_memory" {
  description = "Fargate task memory (MiB)"
  type        = number
  default     = 512
}

variable "desired_count" {
  description = "Number of ECS tasks to run"
  type        = number
  default     = 2
}

variable "container_image_tag" {
  description = "Docker image tag to deploy from ECR"
  type        = string
  default     = "latest"
}

variable "domain_name" {
  description = "Full domain name for the UI (e.g. selfserve.example.com)"
  type        = string
}

variable "hosted_zone_id" {
  description = "Route53 Hosted Zone ID for the parent domain (e.g. example.com)"
  type        = string
}
