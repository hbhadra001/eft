# Architecture Overview – Angular Self-Serve File Transfer Web Application

## 1. Executive Summary
This document outlines the architecture for the *Self-Serve File Transfer Web Application* built with Angular.  
We compare multiple hosting approaches depending on organizational constraints:

- **Option A**: Angular SPA on **S3 + CloudFront** (public/partner-facing).  
- **Option B**: Angular SPA on **ECS Fargate + Internal ALB** (private intranet).  
- **Option C**: Angular Universal SSR on **Node + NGINX (Fargate)**.  

## 2. High-Level Architectures

### Option A – S3 + CloudFront
```
Browser ─HTTPS─> CloudFront ─OAC─> S3 (Angular dist/)
        └────JWT────> API Gateway ─> Lambda/ECS ─> DDB/S3/StepFn/SQS/EventBridge
```

### Option B – ECS + Internal ALB
```
Corp/VPN ─HTTPS+OIDC─> Internal ALB ─> Fargate (NGINX: Angular dist/)
                                   └> Private API GW (VPC Link) → Lambda/ECS → DDB/S3/StepFn/SQS
```

### Option C – Angular Universal (SSR)
```
Browser ─HTTPS─> ALB (OIDC) ─> NGINX ─> Node (Angular Universal SSR)
                                    └> API Gateway/Lambda/ECS → DDB/S3/StepFn/EventBridge
```

## 3. Disaster Recovery & Multi-Region
- **S3/CloudFront**: S3 CRR for UI assets; Route53 failover for APIs.  
- **ECS**: Deploy multi-region ECS services, replicate ECR, use Route53 health checks.  
- **State**: Use DynamoDB Global Tables for active-active metadata.  

## 4. Success Metrics
- Onboarding time < 15 minutes.  
- Portal availability ≥ 99.9% (S3/CF) or ≥ 99.5% (ECS).  
- API p95 latency < 500ms.  
- File job success rate ≥ 99.9%.  

## 5. Service Level Objectives (SLOs)
- Availability: 99.9% (S3/CF), 99.5% (ECS).  
- Job creation latency < 5s.  
- Error budget < 0.1% failed API calls/month.  

## 6. Monitoring & Observability
- **Frontend**: S3/CF logs or ALB logs; CloudWatch RUM.  
- **Backend**: API Gateway, Lambda, Step Functions metrics; DDB throttles.  
- **Alerts**: Job failures via SNS/Slack; error spikes via CloudWatch alarms.  

## 7. Troubleshooting
- UI not loading: check S3 OAC/CloudFront invalidations or ALB target health.  
- Upload failures: validate presigned URL, IAM role policies.  
- Workflow errors: review Step Functions execution history, EventBridge DLQ.  
