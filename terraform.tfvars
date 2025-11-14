# Copy this file to terraform.tfvars and update values as needed

project_name        = "selfserve-ui"
aws_region          = "us-west-2"
vpc_cidr            = "10.0.0.0/16"
public_subnet_cidrs = ["10.0.1.0/24", "10.0.2.0/24"]
ecr_repo_name       = "selfserve-angular-ui"
container_cpu       = 256
container_memory    = 512
desired_count       = 2
container_image_tag = "v1"

# Replace with your own domain and hosted zone
domain_name    = "selfserve.abc.com"
hosted_zone_id = "Z0792415364UCQYBG2EA3"
