# Current vs Target Architecture – Self-Serve File Transfer

## 1. Comparison Table

| Area | Current State | Target (S3 Hosting) | Target (ECS Fargate Hosting) |
|------|---------------|---------------------|------------------------------|
| **UI Hosting** | Manual/Ad-hoc | S3 bucket + CloudFront | ECS Fargate + ALB |
| **Access** | Limited internal scripts | Public/partner access via Cognito/OIDC | Intranet OIDC with ALB |
| **TLS** | Manual cert mgmt | CloudFront + ACM | ALB + ACM |
| **Scalability** | Manual | Auto-scale (global) | Auto-scale (tasks) |
| **Ops Effort** | High | Very low | Medium |
| **Auth/SSO** | Not standardized | Browser token-based | ALB OIDC |
| **DR** | Manual failover | S3 CRR + Route 53 | ECS multi-region + Route 53 |
| **Security** | Limited | S3 policies, WAF | VPC isolation, SGs, WAF |

## 2. Success Matrix

| Dimension | Target (S3) | Target (ECS) |
|-----------|-------------|--------------|
| **Cost efficiency** | Excellent | Moderate |
| **Global reach** | High (CloudFront) | Moderate (intranet) |
| **Compliance** | Moderate (Cognito-based) | Strong (OIDC + VPC isolation) |
| **Ease of operations** | Very high | Medium |
| **Feature extensibility** | Limited (static only) | High (SSR, headers, auth) |
