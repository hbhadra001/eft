# Detailed Component Design – Self-Serve File Transfer

## 1. Option A – S3 Static Website
- **S3 bucket**: host UI build artifacts.  
- **CloudFront**: caching, TLS, SPA rewrites.  
- **API Gateway + Lambda**: presigned URLs, onboarding APIs.  
- **DynamoDB**: configs, jobs, audit.  
- **EventBridge + SQS + Step Functions**: job orchestration.  
- **SNS/SES**: notifications.  

## 2. Option B – ECS Fargate Web Server
- **ECS Fargate (NGINX/Node)**: deliver UI or SSR.  
- **Internal ALB**: TLS termination, OIDC auth, WAF.  
- **Private API Gateway (VPC Link)**: secure APIs.  
- **VPC endpoints**: S3, DynamoDB, Secrets, Logs.  
- **Step Functions/EventBridge**: workflows.  
- **CloudWatch**: logging, metrics, alarms.  

## 3. Pros & Cons by Component

| Component | S3 Hosting | ECS Hosting |
|-----------|------------|-------------|
| **Frontend** | Cheap, simple | Flexible, secure |
| **TLS** | Requires CloudFront | Native ALB ACM |
| **Auth** | SPA Cognito tokens | ALB OIDC |
| **Scaling** | Infinite | Configurable |
| **Headers/SSR** | Limited | Full control |
| **Ops** | Minimal | Moderate |

## 4. SLOs
- **UI Availability**: 99.9% (S3+CF) / 99.5% (ECS+ALB).  
- **API p95 Latency**: < 500 ms.  
- **File Job Success Rate**: ≥ 99.9%.  
- **Auth Success Rate**: ≥ 99.5%.  

## 5. Monitoring & Troubleshooting
- **Monitoring**:  
  - S3/CloudFront or ALB access logs.  
  - CloudWatch dashboards for API Gateway, Lambda, Step Functions.  
  - DynamoDB read/write capacity alerts.  
- **Troubleshooting**:  
  - S3 hosting: check OAC, cache invalidations.  
  - ECS: check ALB target health, container logs.  
  - API failures: CloudWatch logs, DLQs, Step Functions error traces.  
