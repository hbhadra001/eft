awesome — here’s a **complete C2 (Container) visual text diagram** for your platform, plus **detailed descriptions** of every runtime container/service and the key interfaces between them. It’s formatted to drop straight into your ARB doc.

---

# C2 — Containers (Deployable/Runtime Building Blocks)

```
Global Edge
===========

            +---------------------------------------------------------------+
            |                         Route 53 (DNS)                        |
            |    A/AAAA latency alias:  app.<domain>, api.<domain>         |
            +-------------------+---------------------------+---------------+
                                |                           |
                                | (to nearest healthy)      | (to nearest healthy)
                                v                           v

Region A: us-west-2 (Active)                                   Region B: us-east-1 (Active)
==================================================             ==============================================
 VPC (10.40.0.0/16), 3 Public + 3 Private AZs                   VPC (10.50.0.0/16), 3 Public + 3 Private AZs
 IGW, NAT GW x3, SGs, optional VPC Endpoints                    IGW, NAT GW x3, SGs, optional VPC Endpoints

   Public Subnets (a,b,c)                                          Public Subnets (a,b,c)
   ------------------------                                         ------------------------
   +----------------------------+                                   +----------------------------+
   |  WAF (optional, managed)   |                                   |  WAF (optional, managed)   |
   +-------------+--------------+                                   +-------------+--------------+
                 |                                                                |
   +-------------v--------------+                                   +-------------v--------------+
   |  Application Load Balancer |                                   |  Application Load Balancer |
   |  (HTTPS 443, HTTP->HTTPS)  |                                   |  (HTTPS 443, HTTP->HTTPS)  |
   +-------------+--------------+                                   +-------------+--------------+
                 |  Targets: ECS (IP mode)                                         |  Targets: ECS (IP mode)
                 |                                                                  |
   Private Subnets (a,b,c)                                            Private Subnets (a,b,c)
   -------------------------                                           -------------------------
   +-------------+--------------+                                   +-------------+--------------+
   | ECS Service (Fargate)      |                                   | ECS Service (Fargate)      |
   | NGINX serves Angular SPA   |                                   | NGINX serves Angular SPA   |
   | 3 tasks (1 per AZ)         |                                   | 3 tasks (1 per AZ)         |
   +-------------+--------------+                                   +-------------+--------------+

   (Browser loads SPA from ALB → ECS. SPA calls API with Bearer token)

   API Tier (Regional)                                              API Tier (Regional)
   -------------------                                              -------------------
   +-------------+--------------+                                   +-------------+--------------+
   | API Gateway (HTTP API)     |<-- custom domain: api.<domain> -->| API Gateway (HTTP API)     |
   |  CORS=app.<domain>, Logs   |                                   |  CORS=app.<domain>, Logs   |
   +-------------+--------------+                                   +-------------+--------------+
                 |  JWT Authorizer (Okta issuer/audience)                         |  JWT Authorizer (Okta)
                 v                                                                v
   +-------------+--------------+                                   +-------------+--------------+
   |  Lambda: onboarding_api    |                                   |  Lambda: onboarding_api    |
   |  scope/group checks        |                                   |  scope/group checks        |
   +-------------+--------------+                                   +-------------+--------------+
                 |  boto3 DDB                                                    |  boto3 DDB
                 v                                                                v
   +-------------+--------------+       <=== Global Tables Replication ===>      +-------------+--------------+
   | DynamoDB Table (Replica A) | <------------------------------------------->  | DynamoDB Table (Replica B) |
   | GSIs: byCustomer/byStatus  |                                               | GSIs: byCustomer/byStatus  |
   +----------------------------+                                               +----------------------------+

   Shared per Region
   -----------------
   +------------------------+   +-------------------+   +-----------------+   +----------------------+
   | CloudWatch (Logs/Mets) |   | Secrets Manager   |   | KMS (CMKs)      |   | ECR (images+scan+rep)|
   +------------------------+   +-------------------+   +-----------------+   +----------------------+

External Identity (Global)
--------------------------
+------------------------------------------------------------------------------------------------------+
|  Okta (IdP): OIDC PKCE, Custom Authorization Server (issuer), scopes (read/write), groups (admin)   |
+------------------------------------------------------------------------------------------------------+
```

---

# C2 — Detailed Container/Service Descriptions

| #  | Container / Service                            | Runtime / Scope                     | Purpose & Responsibilities                                                                     | Interfaces (Ports/Proto)                                          | Scaling & HA                                                    | Security & Config                                                                                                       |                                                                            |
| -- | ---------------------------------------------- | ----------------------------------- | ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| 1  | **Route 53 (DNS)**                             | Global                              | Latency-based routing and regional failover for `app.<domain>` and `api.<domain>`.             | DNS A/AAAA alias to ALB & API custom domains                      | Global, multi-POP                                               | Health checks on ALB & API; TTL 30–60s                                                                                  |                                                                            |
| 2  | **AWS WAF** (optional, recommended)            | Per region (edge for ALB & API)     | Filters common exploits (SQLi, XSS, bots), rate limits.                                        | Inline with ALB (L7) and API Gateway                              | Managed, multi-AZ                                               | AWS Managed rules + IP reputation; JSON logs to S3                                                                      |                                                                            |
| 3  | **ALB (Application Load Balancer)**            | Per region, public subnets (3 AZs)  | TLS termination; serves Angular SPA from ECS; 80→443 redirect; health checks.                  | 80/443 from Internet → target group (ECS IP:80)                   | Multi-AZ; targets spread across 3 AZs                           | ACM cert; SG: 80/443 from 0.0.0.0/0; WAF attached; idle timeout 60s                                                     |                                                                            |
| 4  | **ECS Cluster + Service (Fargate)**            | Per region, private subnets (3 AZs) | Hosts **NGINX** container to serve the **Angular SPA** (static assets + SPA routing fallback). | ALB → container :80 (HTTP); ECR for images                        | **Desired 3** (1 per AZ); auto-scale on CPU/Mem/ALBRequestCount | Task SG only allows from ALB SG; awslogs to CloudWatch; NGINX with HSTS, XFO, XCTO, Referrer-Policy, **CSP (Okta+API)** |                                                                            |
| 5  | **ECR (Elastic Container Registry)**           | Per account/region                  | Stores NGINX+SPA images; scans on push; replicates across regions.                             | ECR API/DKR                                                       | Regional; replication enabled                                   | Scan-on-push; lifecycle rules; IAM least-privilege for push/pull                                                        |                                                                            |
| 6  | **API Gateway (HTTP API)** + **Custom Domain** | Per region                          | Receives SPA API calls; performs **JWT validation** via Authorizer; forwards to Lambda.        | HTTPS 443; identity source: `Authorization` header                | Regional, multi-AZ                                              | CORS: allow only `https://app.<domain>`; access logs; WAF optional                                                      |                                                                            |
| 7  | **JWT Authorizer (Okta)**                      | Config on API GW                    | Validates JWTs from Okta against **issuer** and **audience**; rejects invalid before Lambda.   | n/a (control plane)                                               | n/a                                                             | Issuer: `https://<okta>/oauth2/<authz-server>`; Audience: `api.onboarding`; cache TTL 0–300s                            |                                                                            |
| 8  | **Lambda: `onboarding_api`**                   | Per region (serverless)             | Implements endpoints: POST `/requests`, GET `/requests/{id}`, GET `/requests?customerId        | status`; enforces scopes/groups; idempotent writes; logs/metrics. | Invoked by API GW; SDK to DynamoDB                              | Auto scales; concurrency limits/alarms                                                                                  | IAM least-privilege (DDB read/write + logs); optional DLQ; structured logs |
| 9  | **DynamoDB (Global Table)**                    | Replicated across both regions      | Stores onboarding metadata; **GSIs** for by-customer & by-status; PITR.                        | AWS SDK (HTTPS)                                                   | Serverless, highly available                                    | PAY_PER_REQUEST; PITR ON; SSE-KMS CMK; conditional writes for idempotency; Streams optional                             |                                                                            |
| 10 | **CloudWatch (Logs/Metrics/Alarms)**           | Per region                          | Centralized logs (ALB/ECS/Lambda/API); metrics & alarms (5xx, throttles, replication lag).     | HTTPS agent/APIs                                                  | Regional                                                        | Retention 14–90d; SNS/PagerDuty alerts; dashboards per region + global                                                  |                                                                            |
| 11 | **Secrets Manager**                            | Per region                          | Stores API secrets or integration credentials (if/when needed).                                | HTTPS                                                             | Regional                                                        | Rotation where applicable; IAM scoping to Lambda only                                                                   |                                                                            |
| 12 | **KMS (CMKs)**                                 | Per region                          | Encryption for DDB, logs, and secrets; access audit.                                           | n/a                                                               | Regional                                                        | Key policies least-privilege; rotation per policy                                                                       |                                                                            |
| 13 | **VPC & Networking** (IGW, NAT x3, Endpoints)  | Per region                          | Network isolation; NAT for private tasks; optional endpoints for S3, DDB, CW Logs, ECR.        | Layer-3 routing                                                   | Multi-AZ                                                        | One NAT per AZ; SGs over NACLs; endpoint policies restrict egress                                                       |                                                                            |
| 14 | **Okta (IdP)**                                 | External (global)                   | OIDC PKCE login for SPA; issues ID/Access/Refresh; groups/roles in claims; MFA policies.       | OIDC/OAuth2 over HTTPS                                            | SaaS SLA                                                        | Custom AuthZ Server; redirect URIs & CORS locked; refresh token rotation                                                |                                                                            |

---

## Key Interfaces (C2-level Contracts)

* **Browser → ALB (HTTPS 443):** Fetch SPA (HTML/JS/CSS); HSTS; CSP allows `*.okta.com` and `api.<domain>`.
* **Browser (SPA) → API (HTTPS 443):** `Authorization: Bearer <access_token>` header; JSON REST.
* **API Gateway → JWT Authorizer:** Validates `iss`/`aud`/`exp`/signature; blocks unauthenticated calls.
* **API Gateway → Lambda:** Event v2; passes validated JWT claims under `requestContext.authorizer.jwt.claims`.
* **Lambda → DynamoDB:** SDK calls; conditional Put for idempotency (`attribute_not_exists(pk)`), Query via GSIs.
* **ALB → ECS tasks:** Health check path `/health` (200–399); target type = **ip**; one task per AZ.
* **ECR Replication:** Ensures the same image tag exists in both regions for consistent deploys.
* **Route 53 Latency Routing:** Directs each user to the nearest healthy **region**; health checks on ALB and API domain.

---

## Non-Functional Concerns at C2 (what the board will ask)

* **Availability:** Active-active across **us-west-2** and **us-east-1**; **3 AZs** per region; one ECS task per AZ minimum; DynamoDB Global Tables.
* **Security:** Okta OIDC PKCE; JWT Authorizer in API GW; WAF; IAM least-privilege; KMS; Secrets Manager; strict CORS & CSP.
* **Scalability:** ALB scales L7; ECS service autoscaling; API Gateway & Lambda scale elastically; DynamoDB is serverless.
* **Observability:** CloudWatch logs/metrics/alarms; per-region dashboards; 5xx, latency, throttles, DDB replication lag.
* **Cost Controls:** PAY_PER_REQUEST DDB; ECS right-sizing; consider VPC endpoints to reduce NAT traffic; ALB/WAF logging sampling.
* **DR & Failover:** Route 53 health checks; simulate AZ/region impairments; validate idempotency & replication on recovery.

---

### Short “In a sentence” blurbs (for slide notes)

* **ALB + ECS (NGINX):** “Delivers the Angular SPA over HTTPS, scales across three AZs, and terminates TLS/WAF at the edge.”
* **API GW + JWT Authorizer:** “Validates Okta tokens at the door, ensuring only trusted, scoped calls reach our functions.”
* **Lambda:** “Stateless business logic that enforces scopes/roles and writes/query onboarding metadata.”
* **DynamoDB Global Tables:** “Active-active storage replicated across regions with PITR and KMS encryption.”

If you want, I can also provide a **C2 Mermaid diagram** version to paste into Confluence alongside this ASCII.
