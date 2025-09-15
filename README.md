Here’s a clear, no-nonsense comparison of the two ways to host your **Self-Serve File Transfer** UI, tailored to your stack (Transfer Family, S3, EventBridge, SQS, Step Functions, Lambda, DynamoDB, API Gateway).

# Quick decision cheat-sheet

* **Pick S3 static site** if your UI is a pure SPA (React/Angular), no server-side rendering, and you want the simplest, lowest-ops setup.
* **Pick ECS Fargate web server** if you need private/intranet-only access without CloudFront, enterprise SSO at the “edge,” server-side logic/SSR, custom headers/middleware, or tight network controls (VPC-only).

---

# Side-by-side comparison (key criteria)

| Area                      | S3 Static Website Hosting                                                                                                                    | ECS Fargate (web server behind ALB)                                                      |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| **Ops complexity**        | Very low (upload files)                                                                                                                      | Medium (containers, ALB, autoscaling)                                                    |
| **Cost profile**          | Lowest for static assets; pay per GB + requests                                                                                              | Higher: Fargate task hours + ALB + data; still manageable for intranet loads             |
| **TLS/HTTPS**             | **S3 website endpoint = HTTP only**. For HTTPS you normally use CloudFront. If CloudFront not allowed→ use reverse proxy pattern (see below) | Full TLS via ALB + ACM; easy custom domain; WAF supported                                |
| **Private/Intranet-only** | Tricky without CloudFront; options require corporate reverse proxy or alternative patterns                                                   | Simple: internal ALB, private subnets; no public internet exposure                       |
| **Auth/SSO**              | Browser-side (Cognito Hosted UI/OIDC) → tokens in SPA                                                                                        | ALB OIDC (Azure AD/Okta/etc.) at the edge, or app-level auth; centralized session policy |
| **Caching/latency**       | Excellent with CloudFront; without it, regional only                                                                                         | App can set cache headers; ALB isn’t a CDN; add your own cache (Nginx) if needed         |
| **Routing/rewrites**      | S3 website endpoint supports index fallback; limited edge logic without CloudFront                                                           | Full control: rewrites, headers, CSP, HSTS, redirects, compressed assets, etc.           |
| **Security controls**     | Bucket policies, OAC via CloudFront; limited header control without CloudFront                                                               | Security headers, WAF on ALB, SGs, NACLs, private link to backends, mTLS (if desired)    |
| **Real-time updates**     | Use API Gateway WebSocket/SSE via API calls                                                                                                  | Native WebSockets at app or via API GW; easier sticky sessions if needed                 |
| **CI/CD**                 | Upload build artifacts; invalidations (if CF)                                                                                                | Standard container CI/CD (ECR→ECS blue/green)                                            |
| **DR / Multi-region**     | Replicate bucket; CloudFront global if allowed                                                                                               | Duplicate services per region; route via Route 53; state externalized (DDB)              |
| **When it shines**        | Public static SPA, minimal ops, global scale (CF)                                                                                            | Intranet, SSO at edge, SSR/middleware, strict network isolation, “no CloudFront” orgs    |

---

# Architecture A: S3 Static Website Hosting

## When to use

* SPA (React/Angular) calling **API Gateway + Lambda/ECS**.
* Public or broad internal audience, minimal server logic.
* You can use **CloudFront** (best) — or you accept alternative patterns if CloudFront is not allowed.

## High-level flow (public, with API Gateway)

```
[User Browser]
     |
     | HTTPS
     v
[CloudFront]* --> [S3 (static UI)]
     |
     | HTTPS (JWT/Cognito)
     v
[API Gateway] --> [Lambda/ECS APIs] --> [DynamoDB/S3/StepFn/EventBridge/SQS]
*If CloudFront not allowed, see “No-CloudFront variants” below.
```

## Step-by-step (baseline)

1. **Build the SPA**

   * React/Angular build → `/dist` or `/build` folder with `index.html`, JS/CSS assets.
2. **Create S3 bucket** (e.g., `ui-eft-portal-prod`)

   * Enable **Static website hosting**; set `index.html` as index; `error.html` fallback.
   * Upload build artifacts.
   * Configure **bucket policy** for read access *only through your chosen front door* (CloudFront OAC if using CF).
3. **(Recommended) Add CloudFront**

   * Origin: S3 (REST endpoint + OAC).
   * ACM cert + custom domain (`ui.company.com`).
   * Behaviors: SPA rewrite (all → `index.html`), cache static assets, add security headers via functions (optional).
   * Route 53 CNAME (e.g., `ui.company.com` → CF).
4. **Auth (front-end)**

   * Integrate **Cognito Hosted UI** or corporate OIDC using OAuth/OIDC libs.
   * Store ID token; attach to API calls (Authorization header).
5. **APIs & CORS**

   * **API Gateway** (HTTP or REST) → Lambda/ECS for: onboarding flows, presigned S3 URLs, job status, etc.
   * Configure **CORS** (origins=UI domain, headers, methods).
6. **Uploads & downloads**

   * Use **presigned S3 URLs** from your backend; upload/download directly S3<→Browser.
   * Use V4 signatures; set object metadata (tenant/job IDs).
7. **Observability**

   * S3 access logs (optional), CloudFront logs, CloudTrail.
   * Frontend errors via RUM tools; API metrics in CloudWatch.
8. **DR/Multi-region**

   * Turn on **S3 CRR** for UI assets; promote secondary on regional failure.
   * API layer: deploy multi-region with Route 53 health checks (if required).

### Pros

* **Simplest & cheapest** for a pure SPA.
* Scales automatically; no servers to patch.
* With CloudFront: global performance, DDoS mitigation, TLS easy.

### Cons

* **Without CloudFront** you don’t get HTTPS on S3 website endpoint.
* Limited edge logic without CloudFront; custom headers/tricky rewrites need a proxy.
* Intranet/private access is awkward without a front door (CF, proxy, or ALB pattern).

### “No-CloudFront” variants (if CloudFront is disallowed)

You have three realistic options:

**A1. Corporate reverse proxy** (F5/NGINX) doing TLS + auth, fetching S3 assets.

* Pros: Keeps S3 for hosting; adds HTTPS/SSO.
* Cons: Extra infra to run/operate; need careful caching and SPA rewrites.

**A2. API Gateway + Lambda for static** (serve assets from S3 via Lambda).

* Pros: Stays in AWS managed space; HTTPS built-in.
* Cons: Inefficient/\$\$ for large assets; you reinvent CDN; not recommended for heavy static.

**A3. Move static hosting to ECS/NGINX** (…which is Architecture B).

---

# Architecture B: ECS Fargate Cluster with Web Server

## When to use

* **Intranet/private-only** portal (internal ALB), **no CloudFront allowed**.
* Need **enterprise SSO at the edge** (ALB OIDC), custom headers/policies, URL rewrites, or **SSR** (Next.js/Nest SSR).
* You want all traffic contained **inside a VPC** with service endpoints.

## High-level flow (private)

```
[Corporate Network/VPN/ZTNA]
          |
          | HTTPS + OIDC
          v
  [Internal ALB + WAF]  --(auth)-->  [ECS Fargate: NGINX/Node SSR]
          |
          | HTTPS (service-to-service)
          v
 [API Gateway (Private + VPC Link) or ECS APIs] -> [Lambda/ECS]
          |
          +--> [DynamoDB/S3 (via VPC endpoints)/StepFn/EventBridge/SQS]
```

## Step-by-step (baseline)

1. **Containerize UI**

   * For pure static: build assets into an **NGINX** image (copy `/build` → `/usr/share/nginx/html` with SPA fallback).
   * For SSR: build Node/Next.js image.
2. **Push to ECR**

   * Private ECR repo (prod/stage tags).
3. **Network**

   * VPC with **private subnets** for ECS tasks; **internal ALB** in private subnets.
   * **VPC endpoints**: S3 (Gateway), ECR/ECR-DKR, CloudWatch Logs, Secrets Manager, SSM.
   * (Optional) NAT GW if tasks need outbound internet; otherwise rely on endpoints.
4. **Security groups**

   * ALB SG: ingress from corp CIDRs/VPN/ZTNA only; egress to ECS SG.
   * ECS SG: ingress from ALB SG; egress to service endpoints.
5. **ALB + TLS + WAF**

   * Internal ALB with **ACM** cert.
   * Optional **AWS WAF** attached to ALB for L7 protections.
   * **OIDC authentication** on ALB (Azure AD/Okta) → inject identity headers to app.
6. **ECS Service**

   * Fargate service (1–3 tasks min; autoscale on req count/CPU).
   * Health checks `/healthz`.
   * For static: enable gzip/brotli in NGINX; SPA fallback (`try_files`).
7. **APIs**

   * Private **API Gateway** with **VPC Link** to private NLB/ALB or direct ECS service; or call Lambda via private integrations.
   * Alternative: Host backend on ECS and use Cloud Map service discovery.
8. **S3 access & uploads**

   * ECS task role with **S3 policy** for presigned URL helper endpoints.
   * Upload/download directly browser↔S3 using presigned URLs; S3 accessed through **Gateway Endpoint** (no public internet).
9. **Observability**

   * ALB access logs → S3; ECS logs → CloudWatch; metrics + X-Ray (if SSR).
   * Dashboards for request rate, p95, 5xx, task health.
10. **CI/CD**

* CodeBuild/CodePipeline or GitHub Actions: build image → ECR → ECS deploy (blue/green optional).
* DB/infra handled via Terraform.

11. **DR/Multi-region**

* Replicate ECR/S3 assets; duplicate ECS service in secondary region.
* Route 53 failover/latency routing for the intranet DNS if applicable.
* Keep state in DDB (global tables optional) and S3.

### Pros

* **Private by design** (internal ALB); easy **HTTPS** without CloudFront.
* **Enterprise SSO at ALB** (OIDC), centralized auth/logging.
* Full **control over headers, rewrites, SSR**, compression, caching rules.
* Tight **VPC isolation** + service endpoints; clean audit trail.

### Cons

* Higher **cost/ops** than S3 static.
* Capacity planning for **autoscaling** (min tasks for HA).
* You manage container images, web server config, and deployments.

---

# How each supports your **Self-Serve File Transfer** flows

| Capability                   | S3 Static Site                                                 | ECS Fargate Web Server                                                 |
| ---------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------- |
| **Customer onboarding UI**   | SPA forms → API GW/Lambda for validation & config writes (DDB) | Same, or add server middleware for validation and policy enforcement   |
| **JSON-driven workflows**    | SPA calls backend to store JSON configs in DDB/S3              | Same; can add server-side schema validation (AJV) at web tier          |
| **Presigned S3 uploads**     | Backend issues presigned URLs; SPA PUTs directly               | Same; optionally proxy via ECS if you want content scanning first      |
| **Job status/notifications** | Poll API or use API GW WebSockets/SSE                          | WebSockets/SSE directly from ECS or via API GW                         |
| **RBAC / multi-tenant**      | Token-based (Cognito/JWT) enforced at APIs                     | Enforce at ALB (group claims) + in app; supports header-based policies |
| **Auditability**             | API Gateway/CloudTrail logs; limited at S3 for UI              | Full ALB access logs + ECS logs + API logs                             |

---

# Security & compliance notes (both options)

* **Least-privilege IAM** for UI upload features (presigned URLs), DDB tables (configs/jobs), Step Functions (job orchestration), SQS/SNS/EventBridge.
* **CORS**: lock to your UI domain; allow only required methods/headers.
* **Security Headers**: CSP, HSTS, X-Frame-Options, etc. (easier to enforce on ECS/NGINX; on S3 you typically use CloudFront functions or the reverse proxy).
* **PII/PHI**: terminate TLS at the first hop (ALB/CloudFront/reverse proxy). For S3-only without CF, don’t serve PII over HTTP.

---

# Concrete recommendations (pick your scenario)

1. **Public or partner-facing SPA, CloudFront allowed**
   → **S3 + CloudFront** for UI, **API Gateway + Lambda/ECS** for APIs. Lowest cost/ops, global performance.

2. **Intranet / private only, CloudFront not allowed**
   → **ECS Fargate (NGINX)** behind **internal ALB** with **OIDC SSO**, VPC endpoints for S3/DDB/etc. This is the cleanest way to get **HTTPS**, **SSO**, and **tight VPC isolation** without CloudFront.

3. **Need SSR/middleware/advanced headers** (e.g., signed cookies, content scanning pre-upload, dynamic HTML)
   → **ECS Fargate** (Node/Next.js or NGINX + Lua), even if later you front it with CloudFront.

---

# “Do this now” checklists

## A. S3 static (with/without CloudFront)

* [ ] Build SPA → upload to S3 (`index.html`, assets)
* [ ] If **CloudFront allowed**: set OAC, TLS (ACM), SPA rewrites, Route 53
* [ ] If **no CloudFront**: arrange **corporate reverse proxy** for TLS+SSO, or switch to ECS variant
* [ ] Configure CORS on APIs; integrate Cognito/OIDC in SPA
* [ ] Add presigned URL endpoints in API; test PUT/GET
* [ ] Enable logs/monitoring; set lifecycle/CRR for assets

## B. ECS Fargate web server

* [ ] Dockerize UI (NGINX) or SSR (Node) → push to ECR
* [ ] VPC: private subnets, internal ALB, SGs, **VPC endpoints** (S3/ECR/Logs/Secrets)
* [ ] ALB: ACM cert; **OIDC auth** (Azure AD/Okta) + optional WAF
* [ ] ECS Service: min 2 tasks (multi-AZ); autoscaling; health checks
* [ ] API integration: Private API GW + VPC Link or ECS backend
* [ ] Presigned URLs + S3 Gateway Endpoint; enforce IAM conditions (tenant tags)
* [ ] Logs (ALB→S3, ECS→CloudWatch), alarms, dashboards
* [ ] Terraform the whole lot; blue/green deploy

---

# Final guidance

Given your earlier constraint (“no CloudFront”) and **intranet** access with **SSO**, the **ECS Fargate + internal ALB (OIDC)** pattern is the most straightforward, secure, and compliant way to host the UI. If CloudFront becomes acceptable later, you can move the UI back to **S3+CloudFront** and keep the same backend APIs—the UI is a thin layer either way.

If you want, I can turn this into a Confluence-ready set (Architecture Overview, Current vs Target, Detailed Component Design) and add Terraform stubs for both hosting options.






Got it 👍

Here’s how I’ll structure the **Confluence-ready deliverables** for you, covering both **S3 static site** and **ECS Fargate** options:

---

# 📄 Confluence Page Set

## **01\_Architecture\_Overview\.md**

* **Executive Summary**
  Two alternative architectures for the *Self-Serve File Transfer Web Application* were evaluated:

  1. **S3 Static Website Hosting** (low-cost SPA hosting).
  2. **ECS Fargate Web Server** (private intranet hosting with enterprise auth).
* **Visual Text Diagram – High-Level**

### Option A – S3 + API Gateway

```
User Browser --> [CloudFront*] --> [S3 Static Website]
       |                              |
       v                              |
   [API Gateway HTTPS] --> [Lambda/ECS APIs] --> [DDB/S3/StepFn/EventBridge]
*if CloudFront not allowed: replace with reverse proxy
```

### Option B – ECS Fargate + Internal ALB

```
User Browser (Corp/VPN)
        |
        v
 [Internal ALB + OIDC Auth]
        |
        v
  [ECS Fargate Web Server]
        |
        v
 [Private API GW / Lambda / ECS APIs]
        |
        v
 [DDB/S3/StepFn/EventBridge/SQS]
```

* **DR / Multi-Region Section**

  * S3: Cross-Region Replication, Route53 failover for APIs.
  * ECS: Multi-region ECS services + Route53 latency-based routing.

---

## **01b\_Current\_vs\_Target\_SideBySide.md**

| Aspect      | Current State (if any) | Target (S3 Hosting)        | Target (ECS Fargate Hosting) |
| ----------- | ---------------------- | -------------------------- | ---------------------------- |
| UI Hosting  | Manual app, no portal  | S3 bucket + CloudFront     | ECS Fargate + ALB            |
| Access      | Limited                | Public/Partner via Cognito | Intranet/SSO via OIDC        |
| TLS         | Manual cert mgmt       | CloudFront ACM             | ALB ACM                      |
| Scalability | Limited                | Auto-scale via CloudFront  | Auto-scale via Fargate       |
| Ops Effort  | High                   | Very low                   | Medium                       |
| DR          | Manual                 | S3 CRR                     | ECS multi-region             |

---

## **02\_Detailed\_Component\_Design.md**

### **Option A – S3 Static**

* **S3 bucket** (static assets).
* **CloudFront** (TLS, caching, security headers).
* **API Gateway** (REST/HTTP for onboarding, presigned S3 URLs).
* **Lambda** (config handling, file metadata, job orchestration).
* **DynamoDB** (configs, jobs, audit).
* **EventBridge/SQS/SFN** for workflow orchestration.
* **SNS/SES** for notifications.

### **Option B – ECS Fargate**

* **ECS Fargate Service** (UI container, NGINX/Node).
* **ALB** (OIDC auth, TLS, WAF).
* **Private API Gateway + VPC Link** (secure APIs).
* **VPC Endpoints** (S3, DDB, Logs, ECR).
* **Step Functions & EventBridge** (orchestration).
* **CloudWatch** (logs, metrics, dashboards).

### **Pros & Cons (per component)**

* *S3:* lowest ops, but HTTPS without CloudFront is tricky.
* *ECS:* more ops, but supports private intranet, strict SSO, SSR, custom headers.

---

⚙️ Next Step (your choice):

1. I can **expand these Confluence pages into full drafts** (with success matrix, SLOs, and monitoring/troubleshooting sections).
2. Or, I can **add Terraform stubs** for both hosting options (S3 + CloudFront vs ECS + ALB).

👉 Do you want me to start with the **Confluence drafts** or the **Terraform stubs** first?



Perfect 👍 Let’s start with the **Confluence drafts**. I’ll prepare them in a **ready-to-paste format** with headings, tables, and diagrams that match your existing documentation style.

---

# 📄 Draft 01\_Architecture\_Overview

**Title:** Architecture Overview – Self-Serve File Transfer Web Application

---

## **1. Executive Summary**

This document presents two potential architectures for hosting the *Self-Serve File Transfer Web Application*. Both approaches integrate with backend AWS services (API Gateway, Lambda, DynamoDB, S3, Step Functions, EventBridge, SQS, SNS) but differ in how the front-end UI is delivered:

1. **S3 Static Website Hosting** – optimized for cost, simplicity, and global scalability.
2. **ECS Fargate Web Server Hosting** – optimized for private intranet access, enterprise authentication, and stricter security controls.

---

## **2. High-Level Architectures**

### **Option A – S3 Static Website**

```
[User Browser]
     |
     v
 [CloudFront*] ---> [S3 Static Website Hosting]
     |
     v
 [API Gateway] ---> [Lambda/ECS APIs] ---> [DynamoDB/S3/StepFn/EventBridge/SQS]

*If CloudFront not allowed, substitute with corporate reverse proxy.
```

### **Option B – ECS Fargate Web Server**

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

---

## **3. Disaster Recovery & Multi-Region**

* **S3-based**

  * Cross-Region Replication (CRR) for static assets.
  * Route 53 failover for API Gateway endpoints.
* **ECS-based**

  * Duplicate ECS services and ALBs across multiple regions.
  * Route 53 latency-based routing or health check–based failover.
  * Leverage DynamoDB Global Tables for cross-region state sync.

---

# 📄 Draft 01b\_Current\_vs\_Target\_SideBySide

**Title:** Current vs Target Architecture – Self-Serve File Transfer

---

## **1. Comparison Table**

| Area            | Current State            | Target (S3 Hosting)                    | Target (ECS Fargate Hosting)   |
| --------------- | ------------------------ | -------------------------------------- | ------------------------------ |
| **UI Hosting**  | Manual/Ad-hoc, no portal | S3 bucket + CloudFront                 | ECS Fargate + ALB              |
| **Access Type** | Limited internal scripts | Public/partner access via Cognito/OIDC | Private intranet with ALB OIDC |
| **TLS/HTTPS**   | Manual certs             | CloudFront + ACM                       | ALB + ACM                      |
| **Scalability** | Low/manual               | Auto-scale via CloudFront              | Auto-scale via Fargate tasks   |
| **Ops Effort**  | High (manual updates)    | Very low (upload build)                | Medium (CI/CD + container ops) |
| **Auth/SSO**    | Not standardized         | Browser token-based auth (Cognito)     | ALB OIDC with corporate IdP    |
| **DR**          | Manual failover          | S3 CRR + Route53                       | Multi-region ECS + Route53     |
| **Security**    | Limited IAM controls     | Bucket policies + CloudFront WAF       | VPC isolation + SG + WAF       |

---

# 📄 Draft 02\_Detailed\_Component\_Design

**Title:** Detailed Component Design – Self-Serve File Transfer

---

## **1. Option A – S3 Static Website**

* **S3 Bucket** – hosts React/Angular build artifacts.
* **CloudFront (recommended)** – TLS, caching, SPA rewrites, security headers.
* **API Gateway** – REST/HTTP APIs for onboarding and file transfer workflows.
* **Lambda Functions** – presigned S3 URLs, config mgmt, workflow orchestration.
* **DynamoDB** – stores configs, jobs, and audit logs.
* **EventBridge/SQS/Step Functions** – orchestration and workflow routing.
* **SNS/SES** – notifications (success/failure events).

---

## **2. Option B – ECS Fargate Web Server**

* **ECS Fargate Service** – containerized NGINX/Node server to deliver UI.
* **Internal ALB** – TLS termination (ACM), OIDC auth with Azure AD/Okta.
* **Private API Gateway** – exposes APIs via VPC Link.
* **VPC Endpoints** – S3, DynamoDB, Logs, Secrets Manager for private connectivity.
* **Step Functions + EventBridge** – workflow orchestration.
* **CloudWatch** – logging, dashboards, alarms.

---

## **3. Pros & Cons Summary**

| Factor                 | S3 Hosting                       | ECS Hosting                          |
| ---------------------- | -------------------------------- | ------------------------------------ |
| **Cost**               | Very low (pay per GB & requests) | Higher (Fargate + ALB + scaling)     |
| **Ops Complexity**     | Minimal (upload)                 | Medium (containers, scaling, CI/CD)  |
| **Scalability**        | Automatic, global                | Good but requires autoscaling config |
| **Auth Options**       | Cognito/OIDC via SPA             | ALB OIDC or app-level auth           |
| **Intranet Access**    | Hard without CloudFront          | Native via internal ALB              |
| **Custom Headers/SSR** | Limited                          | Full control                         |
| **DR/HA**              | S3 CRR + Route53                 | Multi-region ECS + Route53           |

---

👉 Next step: I can expand each draft with **Success Metrics, SLOs, Monitoring & Troubleshooting sections** to make it fully **architecture-review-board ready**.

Would you like me to **add those sections now** to the drafts, or keep them lean for the first version?




Perfect 👍 — let’s enrich each draft with **Success Metrics, SLOs, Monitoring, and Troubleshooting** so it’s **review-board ready**.

---

# 📄 Draft 01\_Architecture\_Overview (Expanded)

**Title:** Architecture Overview – Self-Serve File Transfer Web Application

---

## **1. Executive Summary**

This document outlines two architecture options for the *Self-Serve File Transfer Web Application*. Both integrate with AWS backend services but differ in the **front-end delivery model**:

1. **S3 Static Website Hosting** – lightweight, cost-efficient, public/partner-facing.
2. **ECS Fargate Web Server Hosting** – enterprise intranet-focused, supports OIDC at edge.

---

## **2. High-Level Architectures**

### **Option A – S3 Static Website**

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

### **Option B – ECS Fargate Web Server**

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

---

## **3. Disaster Recovery & Multi-Region**

* **S3-based**: Cross-Region Replication, Route 53 failover for API Gateway.
* **ECS-based**: Multi-region ECS services + ALBs, Route 53 failover/latency routing, DynamoDB Global Tables for state.

---

## **4. Success Metrics**

* **Onboarding time**: < 15 min from request submission to initial file transfer.
* **Portal availability**: ≥ 99.9% (S3+CloudFront) or ≥ 99.5% (ECS intranet).
* **File transfer initiation latency**: < 2 sec API response.
* **User satisfaction**: ≥ 90% positive feedback.

---

## **5. Service Level Objectives (SLOs)**

* **Availability**:

  * S3 Static Site: 99.9% uptime.
  * ECS Web Server: 99.5% uptime, with multi-AZ failover.
* **Performance**:

  * API Gateway p95 latency < 500 ms.
  * File transfer job creation < 5 sec.
* **Error budget**: < 0.1% failed API calls per month.

---

## **6. Monitoring & Observability**

* **Frontend**:

  * S3/CloudFront access logs (latency, error rate).
  * ALB access logs (ECS option).
  * Browser telemetry (CloudWatch RUM, optional).
* **Backend**:

  * CloudWatch metrics for API Gateway, Lambda, Step Functions.
  * DynamoDB throttling alerts.
* **Alerts**:

  * Transfer job failure events via SNS → Teams/Slack.
  * High error rate alerts in CloudWatch (p95 > 1s).

---

## **7. Troubleshooting Guidance**

* **UI not loading (S3 option)**:

  * Verify S3 bucket policy → OAC.
  * CloudFront invalidation for cache refresh.
* **UI not loading (ECS option)**:

  * Check ALB health checks.
  * Validate OIDC integration logs.
* **File upload/download failures**:

  * Confirm presigned URL validity.
  * Validate IAM role permissions for S3 access.
* **Workflow errors**:

  * Trace in Step Functions execution history.
  * Review EventBridge DLQ and CloudWatch error logs.

---

# 📄 Draft 01b\_Current\_vs\_Target\_SideBySide (Expanded)

**Title:** Current vs Target Architecture – Self-Serve File Transfer

---

## **1. Comparison Table**

| Area            | Current State            | Target (S3 Hosting)                    | Target (ECS Fargate Hosting) |
| --------------- | ------------------------ | -------------------------------------- | ---------------------------- |
| **UI Hosting**  | Manual/Ad-hoc            | S3 bucket + CloudFront                 | ECS Fargate + ALB            |
| **Access**      | Limited internal scripts | Public/partner access via Cognito/OIDC | Intranet OIDC with ALB       |
| **TLS**         | Manual cert mgmt         | CloudFront + ACM                       | ALB + ACM                    |
| **Scalability** | Manual                   | Auto-scale (global)                    | Auto-scale (tasks)           |
| **Ops Effort**  | High                     | Very low                               | Medium                       |
| **Auth/SSO**    | Not standardized         | Browser token-based                    | ALB OIDC                     |
| **DR**          | Manual failover          | S3 CRR + Route 53                      | ECS multi-region + Route 53  |
| **Security**    | Limited                  | S3 policies, WAF                       | VPC isolation, SGs, WAF      |

---

## **2. Success Matrix**

| Dimension                 | Target (S3)              | Target (ECS)                  |
| ------------------------- | ------------------------ | ----------------------------- |
| **Cost efficiency**       | Excellent                | Moderate                      |
| **Global reach**          | High (CloudFront)        | Moderate (intranet)           |
| **Compliance**            | Moderate (Cognito-based) | Strong (OIDC + VPC isolation) |
| **Ease of operations**    | Very high                | Medium                        |
| **Feature extensibility** | Limited (static only)    | High (SSR, headers, auth)     |

---

# 📄 Draft 02\_Detailed\_Component\_Design (Expanded)

**Title:** Detailed Component Design – Self-Serve File Transfer

---

## **1. Option A – S3 Static Website**

* **S3 bucket**: host UI build artifacts.
* **CloudFront**: caching, TLS, SPA rewrites.
* **API Gateway + Lambda**: presigned URLs, onboarding APIs.
* **DynamoDB**: configs, jobs, audit.
* **EventBridge + SQS + Step Functions**: job orchestration.
* **SNS/SES**: notifications.

---

## **2. Option B – ECS Fargate Web Server**

* **ECS Fargate (NGINX/Node)**: deliver UI or SSR.
* **Internal ALB**: TLS termination, OIDC auth, WAF.
* **Private API Gateway (VPC Link)**: secure APIs.
* **VPC endpoints**: S3, DynamoDB, Secrets, Logs.
* **Step Functions/EventBridge**: workflows.
* **CloudWatch**: logging, metrics, alarms.

---

## **3. Pros & Cons by Component**

| Component       | S3 Hosting          | ECS Hosting      |
| --------------- | ------------------- | ---------------- |
| **Frontend**    | Cheap, simple       | Flexible, secure |
| **TLS**         | Requires CloudFront | Native ALB ACM   |
| **Auth**        | SPA Cognito tokens  | ALB OIDC         |
| **Scaling**     | Infinite            | Configurable     |
| **Headers/SSR** | Limited             | Full control     |
| **Ops**         | Minimal             | Moderate         |

---

## **4. SLOs**

* **UI Availability**: 99.9% (S3+CF) / 99.5% (ECS+ALB).
* **API p95 Latency**: < 500 ms.
* **File Job Success Rate**: ≥ 99.9%.
* **Auth Success Rate**: ≥ 99.5%.

---

## **5. Monitoring & Troubleshooting**

* **Monitoring**:

  * S3/CloudFront or ALB access logs.
  * CloudWatch dashboards for API Gateway, Lambda, Step Functions.
  * DynamoDB read/write capacity alerts.
* **Troubleshooting**:

  * S3 hosting: check OAC, cache invalidations.
  * ECS: check ALB target health, container logs.
  * API failures: CloudWatch logs, DLQs, Step Functions error traces.

---

✅ These three drafts now cover **Overview, Current vs Target, and Detailed Design** — plus success metrics, SLOs, monitoring, and troubleshooting.

Do you want me to **package these into a single Confluence-ready zip (Markdown + diagrams)**, or keep them as three standalone pages you can paste directly?





