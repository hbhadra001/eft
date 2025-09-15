# Architecture Overview – Self-Serve File Transfer Web Application

## 1. Executive Summary
This document outlines two architecture options for the *Self-Serve File Transfer Web Application*. Both integrate with AWS backend services but differ in the **front-end delivery model**:  

1. **S3 Static Website Hosting** – lightweight, cost-efficient, public/partner-facing.  
2. **ECS Fargate Web Server Hosting** – enterprise intranet-focused, supports OIDC at edge.  

## 2. High-Level Architectures

### Option A – S3 Static Website
```
[User Browser]
     |
     v
 [CloudFront*] ---> [S3 Static Website Hosting]
     |
     v
 [API Gateway] ---> [Lambda/ECS APIs] ---> [DynamoDB/S3/StepFn/EventBridge/SQS]

*If CloudFront not allowed: replace with corporate reverse proxy.
```

### Option B – ECS Fargate Web Server
```
[User Browser (Corp/VPN)]
        |
        v
 [Internal ALB + OIDC Auth + TLS]
        |
        v
 [ECS Fargate Web Server (NGINX/Node)]
        |
        v
 [Private API Gateway / Lambda / ECS APIs]
        |
        v
 [DynamoDB / S3 / StepFn / EventBridge / SQS]
```

## 3. Disaster Recovery & Multi-Region
- **S3-based**: Cross-Region Replication, Route 53 failover for API Gateway.  
- **ECS-based**: Multi-region ECS services + ALBs, Route 53 failover/latency routing, DynamoDB Global Tables for state.  

## 4. Success Metrics
- **Onboarding time**: < 15 min from request submission to initial file transfer.  
- **Portal availability**: ≥ 99.9% (S3+CloudFront) or ≥ 99.5% (ECS intranet).  
- **File transfer initiation latency**: < 2 sec API response.  
- **User satisfaction**: ≥ 90% positive feedback.  

## 5. Service Level Objectives (SLOs)
- **Availability**:  
  - S3 Static Site: 99.9% uptime.  
  - ECS Web Server: 99.5% uptime, with multi-AZ failover.  
- **Performance**:  
  - API Gateway p95 latency < 500 ms.  
  - File transfer job creation < 5 sec.  
- **Error budget**: < 0.1% failed API calls per month.  

## 6. Monitoring & Observability
- **Frontend**:  
  - S3/CloudFront access logs (latency, error rate).  
  - ALB access logs (ECS option).  
  - Browser telemetry (CloudWatch RUM, optional).  
- **Backend**:  
  - CloudWatch metrics for API Gateway, Lambda, Step Functions.  
  - DynamoDB throttling alerts.  
- **Alerts**:  
  - Transfer job failure events via SNS → Teams/Slack.  
  - High error rate alerts in CloudWatch (p95 > 1s).  

## 7. Troubleshooting Guidance
- **UI not loading (S3 option)**:  
  - Verify S3 bucket policy → OAC.  
  - CloudFront invalidation for cache refresh.  
- **UI not loading (ECS option)**:  
  - Check ALB health checks.  
  - Validate OIDC integration logs.  
- **File upload/download failures**:  
  - Confirm presigned URL validity.  
  - Validate IAM role permissions for S3 access.  
- **Workflow errors**:  
  - Trace in Step Functions execution history.  
  - Review EventBridge DLQ and CloudWatch error logs.  
