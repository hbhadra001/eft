# Detailed Component Design – Angular Self-Serve File Transfer

## 1. Angular App Structure
```
apps/
  portal/
    core/ (AuthService, ApiInterceptor, ConfigService)
    features/ (onboarding, configs, transfers, admin)
    state/ (NgRx or RxJS services)
    environments/ (env.ts, env.prod.ts)
libs/
  ui/ (shared UI)
  models/ (API types)
  data-access/ (SDKs, API clients)
```

- Standalone components + lazy routes.  
- Signals or OnPush change detection.  
- Route guards for RBAC.  

## 2. Cross-Cutting Concerns
- **Auth**: Cognito Hosted UI (public) or ALB OIDC (intranet).  
- **RBAC**: Roles in claims; guards in Angular + backend enforcement.  
- **API Access**: HttpClient + interceptor for tokens.  
- **Config**: runtime `/assets/config.json`.  
- **Uploads**: Presigned S3 PUTs with progress; optional checksum.  

## 3. Backend Interaction
- Onboarding: UI → API → write configs to DDB.  
- Job submission: UI → API → EventBridge → StepFn → targets.  
- Status: poll API or WebSocket/SSE channel.  
- Uploads: presigned S3 URLs; enforce key prefix policies.  

## 4. Deployment Approaches

### S3 + CloudFront
- Build Angular → upload dist/ to S3.  
- CloudFront: OAC, TLS, SPA rewrite, headers.  
- Cognito OIDC PKCE.  

### ECS + ALB
- Multi-stage Docker: Angular build → NGINX serve.  
- Internal ALB + OIDC auth.  
- Private API GW via VPC Link.  
- VPC endpoints: S3, DDB, Logs.  

### Angular Universal
- Docker image: NGINX + Node SSR.  
- ALB + OIDC.  

## 5. Security
- Tokens in memory/sessionStorage only.  
- CSP, HSTS, strict CORS.  
- IAM least privilege for presigned URLs.  
- WAF on CF/ALB.  

## 6. Observability
- RUM metrics (CW RUM or OpenTelemetry).  
- Structured logs with correlation IDs.  
- Dashboards: CF/ALB p95 latency, API error %, StepFn failures, DDB throttles.  

## 7. CI/CD
- Angular build budgets, Jest unit tests, Cypress e2e.  
- Artifact: S3 upload or Docker push (ECR → ECS).  
- Infra: Terraform for S3/CF, ECS/ALB, Cognito, API GW, VPC endpoints.  
- Secrets: SSM or Secrets Manager.  

## 8. DR & Performance
- **S3/CF**: CRR + Route53 failover.  
- **ECS**: replicate services/ECR; Route53 failover; DDB Global Tables.  
- Angular: deferred loading, bundle budgets, gzip/brotli.  
- NGINX: cache headers, gzip, SPA fallback.  
